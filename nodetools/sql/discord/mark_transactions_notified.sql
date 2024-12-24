INSERT INTO discord_notifications (hash)
SELECT UNNEST(%s::varchar[]);