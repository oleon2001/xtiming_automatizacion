
--1. Buscar tickets cerrados
SELECT 
    gt.id AS id_ticket,
    gt.name AS titulo,
    gt.date AS fecha_apertura,
    gt.solvedate AS fecha_solucion,
    gt.status -- 5 = Resuelto, 6 = Cerrado
FROM glpi_tickets gt
WHERE gt.is_deleted = 0 
  AND gt.status > 4
  -- Ajusta las fechas según necesites
  AND gt.solvedate BETWEEN '2024-01-01 00:00:00' AND '2024-12-31 23:59:59';


--2. Buscar técnicos
SELECT 
    gu.id AS id_usuario,
    gu.name AS usuario,
    gu.realname AS apellido,
    gu.firstname AS nombre,
    gp.name AS nombre_perfil
FROM glpi_users gu
INNER JOIN glpi_profiles_users gpu ON gu.id = gpu.users_id
INNER JOIN glpi_profiles gp ON gpu.profiles_id = gp.id
WHERE gp.id = 11;


--3. Buscar técnicos asignados a tickets
SELECT 
    gt.id AS id_ticket,
    gt.name AS titulo,
    CONCAT(gu.realname, ' ', gu.firstname) AS tecnico_asignado
FROM glpi_tickets gt
-- El type = 2 es la clave para filtrar solo a los técnicos asignados
INNER JOIN glpi_tickets_users gtu ON gt.id = gtu.tickets_id AND gtu.type = 2
INNER JOIN glpi_users gu ON gtu.users_id = gu.id
WHERE gt.is_deleted = 0
-- Ejemplo: filtrar por un técnico específico
-- AND gu.name = 'usuario.tecnico';