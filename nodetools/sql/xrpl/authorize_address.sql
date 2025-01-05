INSERT INTO authorized_addresses 
(address, auth_source, auth_source_user_id)
VALUES ($1, $2, $3)
ON CONFLICT (address) 
DO UPDATE SET 
    is_authorized = TRUE,
    deauthorized_at = NULL,
    auth_source = $2,
    auth_source_user_id = $3;