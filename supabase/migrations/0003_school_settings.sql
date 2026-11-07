-- Quickpass Supabase migration 0003: School Settings.
-- One row holds the policies a School sets for itself. The desktop program
-- writes it through Cloud Sync (Service Role Key) and caches it locally; the
-- portal reads the public fields through get_school_settings(), which never
-- returns the Admin Secret Key hash.

CREATE TABLE IF NOT EXISTS public.school_settings (
    id SMALLINT PRIMARY KEY CHECK (id = 1),
    school_language TEXT NOT NULL CHECK (school_language IN ('es', 'en')),
    grades JSONB NOT NULL CHECK (jsonb_typeof(grades) = 'array' AND jsonb_array_length(grades) > 0),
    sections JSONB NOT NULL CHECK (jsonb_typeof(sections) = 'array' AND jsonb_array_length(sections) > 0),
    active_weekdays SMALLINT[] NOT NULL CHECK (
        cardinality(active_weekdays) > 0 AND active_weekdays <@ ARRAY[0, 1, 2, 3, 4, 5, 6]::SMALLINT[]
    ),
    holidays JSONB NOT NULL DEFAULT '[]'::JSONB CHECK (jsonb_typeof(holidays) = 'array'),
    late_threshold TIME NOT NULL,
    cooldown_seconds INTEGER NOT NULL CHECK (cooldown_seconds >= 0),
    admin_secret_key_hash TEXT NOT NULL CHECK (admin_secret_key_hash <> ''),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

COMMENT ON TABLE public.school_settings IS
    'School Settings: a single row (id = 1) of policies the School sets for itself.';
COMMENT ON COLUMN public.school_settings.grades IS
    'Ordered Grade labels; Grade rank N (1-based) is the Nth label, and the last one graduates.';
COMMENT ON COLUMN public.school_settings.active_weekdays IS
    'Weekdays the School is open: 0 = Monday ... 6 = Sunday (ISODOW - 1).';
COMMENT ON COLUMN public.school_settings.holidays IS
    'Dates (YYYY-MM-DD) without classes on otherwise active weekdays.';
COMMENT ON COLUMN public.school_settings.admin_secret_key_hash IS
    'Salted PBKDF2 hash of the Admin Secret Key (pbkdf2_sha256$iterations$salt$hash).';

ALTER TABLE public.school_settings ENABLE ROW LEVEL SECURITY;

REVOKE ALL ON public.school_settings FROM PUBLIC, anon, authenticated;
GRANT ALL ON public.school_settings TO service_role;

CREATE OR REPLACE FUNCTION public.get_school_settings()
RETURNS JSONB
LANGUAGE sql
STABLE
SECURITY DEFINER
SET search_path = public
AS $$
    SELECT jsonb_build_object(
        'school_language', school_language,
        'grades', grades,
        'sections', sections,
        'active_weekdays', to_jsonb(active_weekdays),
        'holidays', holidays,
        'late_threshold', to_char(late_threshold, 'HH24:MI:SS')
    )
    FROM public.school_settings
    WHERE id = 1
$$;

GRANT EXECUTE ON FUNCTION public.get_school_settings() TO anon, authenticated, service_role;
