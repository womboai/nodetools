WITH schema_objects AS (
    -- Tables
    SELECT 
        'Table' as object_type,
        tablename as object_name
    FROM pg_tables 
    WHERE schemaname = 'public'
    AND tablename = ANY(:expected_tables)
    
    UNION ALL
    
    -- Views
    SELECT 
        'View',
        viewname
    FROM pg_views
    WHERE schemaname = 'public'
    AND viewname = ANY(:expected_views)
    
    UNION ALL
    
    -- Functions
    SELECT 
        'Function',
        p.proname
    FROM pg_proc p
    JOIN pg_namespace n ON p.pronamespace = n.oid
    WHERE n.nspname = 'public'
    AND p.proname = ANY(:expected_functions)
    
    UNION ALL
    
    -- Triggers
    SELECT 
        'Trigger',
        t.tgname
    FROM pg_trigger t
    JOIN pg_class c ON t.tgrelid = c.oid
    JOIN pg_namespace n ON c.relnamespace = n.oid
    WHERE n.nspname = 'public'
    AND t.tgname = ANY(:expected_triggers)
    
    UNION ALL
    
    -- Indices
    SELECT 
        'Index',
        c.relname
    FROM pg_index i
    JOIN pg_class c ON i.indexrelid = c.oid
    JOIN pg_namespace n ON c.relnamespace = n.oid
    WHERE n.nspname = 'public'
    AND c.relname = ANY(:expected_indices)
)
SELECT 
    object_type,
    COUNT(*) as count,
    array_agg(object_name ORDER BY object_name) as objects,
    array_length(:all_expected, 1) as expected_count
FROM schema_objects
GROUP BY object_type
ORDER BY object_type;