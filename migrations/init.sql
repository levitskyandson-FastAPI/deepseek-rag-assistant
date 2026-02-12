-- Включение расширения vector
CREATE EXTENSION IF NOT EXISTS vector;

-- Таблица документов
CREATE TABLE IF NOT EXISTS documents (
    id BIGSERIAL PRIMARY KEY,
    content TEXT NOT NULL,
    metadata JSONB DEFAULT '{}',
    embedding vector(1024),
    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW()
);

-- Индекс для быстрого поиска (IVFFlat)
CREATE INDEX IF NOT EXISTS idx_documents_embedding 
ON documents 
USING ivfflat (embedding vector_cosine_ops)
WITH (lists = 100);

-- Функция поиска по косинусному сходству
CREATE OR REPLACE FUNCTION match_documents(
    query_embedding vector(1024),
    match_threshold float,
    match_count int,
    filter_user_id text DEFAULT NULL
)
RETURNS TABLE(
    id bigint,
    content text,
    metadata jsonb,
    similarity float
)
LANGUAGE plpgsql
AS $$
BEGIN
    RETURN QUERY
    SELECT
        documents.id,
        documents.content,
        documents.metadata,
        1 - (documents.embedding <=> query_embedding) as similarity
    FROM documents
    WHERE 
        1 - (documents.embedding <=> query_embedding) > match_threshold
        AND (
            filter_user_id IS NULL 
            OR documents.metadata->>'user_id' = filter_user_id
        )
    ORDER BY similarity DESC
    LIMIT match_count;
END;
$$;