SELECT EXISTS (
    SELECT 1 
    FROM authorized_addresses 
    WHERE address = $1 
    AND is_authorized = TRUE
) as is_authorized;