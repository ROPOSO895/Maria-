-- RUN THIS IN SUPABASE SQL EDITOR
-- (supabase.com > Project > SQL Editor)

-- USERS TABLE
CREATE TABLE IF NOT EXISTS users (
  id UUID DEFAULT gen_random_uuid() PRIMARY KEY,
  username TEXT UNIQUE NOT NULL,
  email TEXT UNIQUE NOT NULL,
  password_hash TEXT NOT NULL,
  created_at TIMESTAMP DEFAULT NOW()
);

-- MESSAGES TABLE (Permanent Memory)
CREATE TABLE IF NOT EXISTS messages (
  id UUID DEFAULT gen_random_uuid() PRIMARY KEY,
  user_id UUID REFERENCES users(id) ON DELETE CASCADE,
  role TEXT NOT NULL CHECK (role IN ('user', 'assistant')),
  content TEXT NOT NULL,
  created_at TIMESTAMP DEFAULT NOW()
);

-- INDEXES for speed
CREATE INDEX IF NOT EXISTS idx_messages_user_id ON messages(user_id);
CREATE INDEX IF NOT EXISTS idx_messages_created ON messages(created_at);

