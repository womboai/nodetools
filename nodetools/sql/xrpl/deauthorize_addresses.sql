UPDATE authorized_addresses 
SET 
    is_authorized = FALSE,
    deauthorized_at = CURRENT_TIMESTAMP
WHERE 
    auth_source = $1 
    AND auth_source_user_id = $2;