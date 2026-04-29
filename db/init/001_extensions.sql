-- =========================================================
-- 001_extensions.sql
-- Ejecutado automaticamente por la imagen postgres en el
-- primer arranque (cuando el volumen pgdata esta vacio).
--
-- - Habilita unaccent.
-- - Crea la text search configuration `spanish_unaccent`
--   que combina unaccent + spanish_stem para FTS sin
--   sensibilidad a acentos.
-- =========================================================

CREATE EXTENSION IF NOT EXISTS unaccent;

-- Crea la configuracion solo si no existe (idempotente)
DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1
        FROM pg_ts_config
        WHERE cfgname = 'spanish_unaccent'
    ) THEN
        EXECUTE 'CREATE TEXT SEARCH CONFIGURATION spanish_unaccent ( COPY = spanish )';
    END IF;
END
$$;

ALTER TEXT SEARCH CONFIGURATION spanish_unaccent
    ALTER MAPPING FOR
        hword, hword_part, word, asciiword, asciihword, hword_asciipart
    WITH unaccent, spanish_stem;
