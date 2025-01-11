WITH user_info AS (
    -- First get the auth source info for the provided address
    SELECT auth_source, auth_source_user_id
    FROM authorized_addresses
    WHERE address = $1
)
UPDATE authorized_addresses
SET 
    is_authorized = TRUE,
    flag_type = NULL,
    flag_expires_at = NULL,
    deauthorized_at = NULL
FROM user_info
WHERE 
    authorized_addresses.auth_source = user_info.auth_source
    AND authorized_addresses.auth_source_user_id = user_info.auth_source_user_id
    AND flag_type IS NOT NULL;