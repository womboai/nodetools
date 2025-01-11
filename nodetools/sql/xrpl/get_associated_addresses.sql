WITH user_info AS (
    SELECT auth_source, auth_source_user_id
    FROM authorized_addresses
    WHERE address = $1
)
SELECT address
FROM authorized_addresses
WHERE 
    auth_source = (SELECT auth_source FROM user_info)
    AND auth_source_user_id = (SELECT auth_source_user_id FROM user_info);