import os
import logging
import json
from datetime import datetime, timedelta
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    Application,
    CommandHandler,
    MessageHandler,
    CallbackQueryHandler,
    ConversationHandler,
    ContextTypes,
    filters,
    PicklePersistence
)
import local_db

logger = logging.getLogger("TelegramBot")

# Estados de la conversación
(
    AWAITING_DESCRIPTION,
    AWAITING_CLIENT,
    AWAITING_HOURS,
    AWAITING_DISTRIBUTION,
    # Nuevos estados para Batch
    AWAITING_BATCH_ACTIVITIES,
    AWAITING_BATCH_RANGE,
    AWAITING_BATCH_CLIENT,
    AWAITING_BATCH_HOURS
) = range(9)

class TelegramService:
    def __init__(self, config):
        self.config = config
        self.token = os.getenv("TG_BOT_TOKEN")
        self.allowed_chat_id = int(os.getenv("TG_CHAT_ID", "0"))
        
        # Configuración del directorio de datos
        base_dir = os.path.dirname(os.path.abspath(__file__))
        self.data_dir = os.path.join(base_dir, "data")
        os.makedirs(self.data_dir, exist_ok=True)
        
        from time_manager import TimeManager
        self.local_db = local_db.LocalDB()
        self.timer = TimeManager(config, self.local_db)
        self.persistence_path = os.path.join(self.data_dir, "bot_persistence.pickle")

    def _is_authorized(self, update: Update) -> bool:
        try:
            return update.effective_chat.id == self.allowed_chat_id
        except:
            return False

    async def start(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        if not self._is_authorized(update): return
        
        await update.message.reply_text(
            "Hola.\n\n"
            "Comandos disponibles:\n"
            "/registrar - Registrar actividad manual simple\n"
            "/batch - Carga masiva (Varios días/tareas)\n"
            "/status - Ver estado del sistema\n"
            "/pendientes - Ver tickets en cola\n"
            "/borrar <ID> - Eliminar un ticket pendiente"
        )

    # --- FLUJO DE REGISTRO BATCH (CARGA MASIVA) ---

    async def iniciar_batch(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        if not self._is_authorized(update): return
        await update.message.reply_text(
            " MODO CARGA MASIVA\n\n"
            "Escribe la lista de actividades (separadas por coma):"
        )
        return AWAITING_BATCH_ACTIVITIES

    async def recibir_batch_actividades(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        text = update.message.text
        # Split por líneas o por comas
        if "\n" in text:
            activities = [a.strip() for a in text.split("\n") if a.strip()]
        else:
            activities = [a.strip() for a in text.split(",") if a.strip()]
        
        if not activities:
            await update.message.reply_text("No entendí la lista. Prueba de nuevo:")
            return AWAITING_BATCH_ACTIVITIES
            
        context.user_data['batch_activities'] = activities
        await update.message.reply_text(
            f"He recibido {len(activities)} actividades.\n\n"
            "Ahora dime el rango de fechas en formato:\n"
            "`DD/MM/YYYY - DD/MM/YYYY`"
            "\n(Ejemplo: `01/03/2024 - 05/03/2024`)",
            parse_mode='Markdown'
        )
        return AWAITING_BATCH_RANGE

    async def recibir_batch_range(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        text = update.message.text.replace(" ", "")
        try:
            if "-" in text:
                start_str, end_str = text.split("-")
            elif "al" in text.lower():
                start_str, end_str = text.lower().split("al")
            else:
                # Si solo pone una fecha, el rango es de un solo dia
                start_str = end_str = text

            start_dt = datetime.strptime(start_str, "%d/%m/%Y")
            end_dt = datetime.strptime(end_str, "%d/%m/%Y")
            
            if start_dt > end_dt:
                await update.message.reply_text("La fecha de inicio no puede ser posterior a la de fin.")
                return AWAITING_BATCH_RANGE

            # Obtener días laborables
            work_days = self.timer.get_working_days_in_range(start_dt, end_dt)
            if not work_days:
                await update.message.reply_text("No hay días laborables (Lunes-Viernes) en ese rango.")
                return AWAITING_BATCH_RANGE
                
            context.user_data['batch_days'] = work_days
            
            # Botones de Cliente
            keyboard = []
            entity_map = self.config.get("entity_map", {})
            for eid, suffix in entity_map.items():
                keyboard.append([InlineKeyboardButton(f"EPA {suffix}", callback_data=f"bclient_{suffix}")])
            keyboard.append([InlineKeyboardButton("Otro / Default", callback_data="bclient_default")])
            
            reply_markup = InlineKeyboardMarkup(keyboard)
            await update.message.reply_text(
                f"Rango aceptado: {len(work_days)} días hábiles detectados.\n"
                "¿Para qué cliente/país son estas tareas?",
                reply_markup=reply_markup
            )
            return AWAITING_BATCH_CLIENT

        except ValueError:
            await update.message.reply_text("Formato de fecha inválido. Usa DD/MM/YYYY.")
            return AWAITING_BATCH_RANGE

    async def recibir_batch_cliente(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        query = update.callback_query
        await query.answer()
        
        client_code = query.data.replace("bclient_", "")
        if client_code == "default":
            context.user_data['client'] = self.config.get("defaults", {}).get("client_fallback")
            context.user_data['project'] = self.config.get("defaults", {}).get("project_fallback")
        else:
            context.user_data['client'] = f"EPA {client_code}"
            context.user_data['project'] = f"Continuidad de Aplicaciones - EPA {client_code}"

        # --- PROCESAMIENTO AUTOMÁTICO DE HORAS ---
        # Obtener horas objetivo de la configuración (default 8)
        hours_per_day = self.config.get("schedule", {}).get("target_hours", 8)
        
        activities = context.user_data['batch_activities']
        days = context.user_data['batch_days']
        client = context.user_data['client']
        project = context.user_data['project']
        
        # Calcular horas por actividad por día
        hours_per_activity = float(hours_per_day) / len(activities)
        total_inserted = 0

        for dt in days:
            for i, act in enumerate(activities):
                ts_id = int(datetime.now().timestamp() * 1000) + total_inserted
                new_entry = {
                    "source": "telegram",
                    "ticket_id": f"BATCH-{ts_id}",
                    "ticket_title": act,
                    "client": client,
                    "project": project,
                    "activity": self.config.get("defaults", {}).get("activity", "Soporte"),
                    "tags": self.config.get("defaults", {}).get("tag", "Soporte"),
                    "manual_hours": hours_per_activity,
                    "target_date": dt.strftime("%Y-%m-%d"),
                    "status": "pending"
                }
                self.local_db.add_pending_ticket(new_entry)
                total_inserted += 1

        await query.edit_message_text(
            " **CARGA MASIVA FINALIZADA**\n\n"
            f"Se han ajustado **{hours_per_day} horas diarias** automáticamente.\n\n"
            f"- Tareas totales: `{total_inserted}`\n"
            f"- Días laborables: `{len(days)}`\n"
            f"- Horas/tarea: `{hours_per_activity:.2f}h` \n\n"
            "Todo está en cola para ser procesado.",
            parse_mode='Markdown'
        )
        return ConversationHandler.END

    # --- COMANDOS INFORMATIVOS ---

    async def status_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        if not self._is_authorized(update): return
        
        pending = self.local_db.get_pending_tickets()
        today_str = datetime.now().strftime("%Y-%m-%d")
        
        # Conteo básico
        pending_count = len(pending)
        today_pending = sum(1 for t in pending if t.get('target_date', '') == today_str or t.get('solvedate', '').startswith(today_str))
        
        msg = (
            f" *Estado del Sistema*\n"
            f"Tickets Pendientes Totales: `{pending_count}`\n"
            f"Pendientes para HOY: `{today_pending}`\n"
        )
        await update.message.reply_text(msg, parse_mode='Markdown')

    async def list_pending(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        if not self._is_authorized(update): return
        
        pending = self.local_db.get_pending_tickets()
        if not pending:
            await update.message.reply_text("No hay nada pendiente, todo limpio.")
            return

        msg = " *Cola de Pendientes:*\n\n"
        for t in pending[:10]: # Limitar a 10 para no spammear
            tid = t.get('ticket_id')
            title = t.get('ticket_title', 'Sin titulo')[:30]
            date = t.get('target_date') or t.get('solvedate', '')[:10]
            source = t.get('source', 'glpi')
            
            msg += f" `{tid}` ({source})\n {date} | {title}...\n\n"
        
        if len(pending) > 10:
            msg += f"... y {len(pending)-10} más."
            
        await update.message.reply_text(msg, parse_mode='Markdown')

    async def delete_pending(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        if not self._is_authorized(update): return
        
        try:
            if not context.args:
                await update.message.reply_text("Dime cual borro. Usa: /borrar <TICKET_ID>")
                return
            
            ticket_id = context.args[0]
            if self.local_db.remove_pending_ticket(ticket_id):
                await update.message.reply_text(f" Ticket `{ticket_id}` eliminado de la cola.", parse_mode='Markdown')
            else:
                await update.message.reply_text(f" No encontré el ticket `{ticket_id}` o ya se procesó.", parse_mode='Markdown')
        except Exception as e:
            await update.message.reply_text(f"Error borrando: {e}")

    # --- FLUJO DE REGISTRO MANUAL ---

    async def iniciar_registro(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        if not self._is_authorized(update): return
        
        await update.message.reply_text("Dime que hiciste:")
        return AWAITING_DESCRIPTION

    async def recibir_descripcion(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        context.user_data['desc'] = update.message.text
        
        keyboard = []
        entity_map = self.config.get("entity_map", {})
        for eid, suffix in entity_map.items():
            keyboard.append([InlineKeyboardButton(f"EPA {suffix}", callback_data=f"client_{suffix}")])
        
        keyboard.append([InlineKeyboardButton("Otro / Default", callback_data="client_default")])
        
        reply_markup = InlineKeyboardMarkup(keyboard)
        await update.message.reply_text("Para que cliente/pais fue?", reply_markup=reply_markup)
        return AWAITING_CLIENT

    async def recibir_cliente(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        query = update.callback_query
        await query.answer()
        
        client_code = query.data.replace("client_", "")
        if client_code == "default":
            context.user_data['client'] = self.config.get("defaults", {}).get("client_fallback")
            context.user_data['project'] = self.config.get("defaults", {}).get("project_fallback")
        else:
            context.user_data['client'] = f"EPA {client_code}"
            context.user_data['project'] = f"Continuidad de Aplicaciones - EPA {client_code}"

        msg = (
            f"Cliente: {context.user_data['client']}\n\n"
            "Cuantas horas totales quieres registrar? (Ej: 2 o 1.5)"
        )
        await query.edit_message_text(msg)
        return AWAITING_HOURS

    async def recibir_horas(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        try:
            horas = float(update.message.text)
            context.user_data['hours'] = horas
        except ValueError:
            await update.message.reply_text("Introduce un numero valido (ej: 2.5).")
            return AWAITING_HOURS

        keyboard = [
            [InlineKeyboardButton("Hoy", callback_data="dist_today")],
            [InlineKeyboardButton("Mañana", callback_data="dist_tomorrow")],
            [InlineKeyboardButton("Dividir en Hoy y Mañana", callback_data="dist_split_2")]
        ]
        reply_markup = InlineKeyboardMarkup(keyboard)
        await update.message.reply_text(" como quieres distribuir las horas?", reply_markup=reply_markup)
        return AWAITING_DISTRIBUTION

    async def finalizar_registro(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        query = update.callback_query
        await query.answer()
        
        dist_mode = query.data
        hours_total = context.user_data['hours']
        desc = context.user_data['desc']
        client = context.user_data['client']
        project = context.user_data['project']
        
        today = datetime.now()
        dates_to_register = []

        if dist_mode == "dist_today":
            dates_to_register.append((today, hours_total))
        elif dist_mode == "dist_tomorrow":
            dates_to_register.append((today + timedelta(days=1), hours_total))
        elif dist_mode == "dist_split_2":
            half = hours_total / 2
            dates_to_register.append((today, half))
            dates_to_register.append((today + timedelta(days=1), half))

        # Generar IDs únicos y guardar
        for i, (dt, hours) in enumerate(dates_to_register):
            # Timestamp + index para evitar colisiones en split
            ts_id = int(datetime.now().timestamp() * 1000) + i
            new_entry = {
                "source": "telegram",
                "ticket_id": f"TEL-{ts_id}",
                "ticket_title": desc,
                "client": client,
                "project": project,
                "activity": self.config.get("defaults", {}).get("activity", "Soporte"),
                "tags": self.config.get("defaults", {}).get("tag", "Soporte"),
                "manual_hours": hours,
                "target_date": dt.strftime("%Y-%m-%d"),
                "status": "pending"
            }
            self.local_db.add_pending_ticket(new_entry)

        msg = (
            "Ya se encolo lo que dijiste\n"
            f"- Actividad: {desc}\n"
            f"- Horas: {hours_total}h\n"
            f"- Distribucion: {dist_mode.replace('dist_', '')}\n\n"
            "El servicio las procesara en la proxima ejecucion."
        )
        await query.edit_message_text(msg)
        return ConversationHandler.END

    async def cancel(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        await update.message.reply_text("Registro cancelado.")
        return ConversationHandler.END

    def run_bot(self):
        """Inicia el bot con persistencia."""
        persistence = PicklePersistence(filepath=self.persistence_path)
        application = Application.builder().token(self.token).persistence(persistence).build()

        conv_handler = ConversationHandler(
            entry_points=[
                CommandHandler("registrar", self.iniciar_registro),
                CommandHandler("batch", self.iniciar_batch)
            ],
            states={
                # Flujo Simple
                AWAITING_DESCRIPTION: [MessageHandler(filters.TEXT & ~filters.COMMAND, self.recibir_descripcion)],
                AWAITING_CLIENT: [CallbackQueryHandler(self.recibir_cliente, pattern="^client_")],
                AWAITING_HOURS: [MessageHandler(filters.TEXT & ~filters.COMMAND, self.recibir_horas)],
                AWAITING_DISTRIBUTION: [CallbackQueryHandler(self.finalizar_registro, pattern="^dist_")],
                
                # Flujo Batch
                AWAITING_BATCH_ACTIVITIES: [MessageHandler(filters.TEXT & ~filters.COMMAND, self.recibir_batch_actividades)],
                AWAITING_BATCH_RANGE: [MessageHandler(filters.TEXT & ~filters.COMMAND, self.recibir_batch_range)],
                AWAITING_BATCH_CLIENT: [CallbackQueryHandler(self.recibir_batch_cliente, pattern="^bclient_")],
                AWAITING_BATCH_HOURS: [MessageHandler(filters.TEXT & ~filters.COMMAND, self.finalizar_batch)],
            },
            fallbacks=[CommandHandler("cancel", self.cancel)],
            name="registro_manual_conversation",
            persistent=True
        )

        application.add_handler(CommandHandler("start", self.start))
        application.add_handler(CommandHandler("status", self.status_command))
        application.add_handler(CommandHandler("pendientes", self.list_pending))
        application.add_handler(CommandHandler("borrar", self.delete_pending))
        
        application.add_handler(conv_handler)

        logger.info("Bot de Telegram iniciado con persistencia.")
        
        # IMPORTANTE: stop_signals=None permite ejecutarlo en un hilo secundario
        application.run_polling(stop_signals=None)
