-- =============================================================================
-- Quickpass Supabase BaaS Schema, Authorized Email Trigger, RLS Policies & RPCs
-- =============================================================================

-- 1. Core School Tables & Indexes
DROP TABLE IF EXISTS public.security_incidents CASCADE;
DROP TABLE IF EXISTS public.web_accounts CASCADE;

CREATE TABLE IF NOT EXISTS public.users (
    id SERIAL PRIMARY KEY,
    badge_uid VARCHAR(32) UNIQUE NOT NULL,
    full_name VARCHAR(255) NOT NULL,
    role VARCHAR(32) NOT NULL,
    email VARCHAR(255) UNIQUE,
    is_active BOOLEAN NOT NULL DEFAULT TRUE,
    created_at VARCHAR(64) NOT NULL
);

CREATE TABLE IF NOT EXISTS public.student_details (
    id SERIAL PRIMARY KEY,
    user_id INTEGER NOT NULL UNIQUE REFERENCES public.users(id) ON DELETE CASCADE,
    grade INTEGER NOT NULL CHECK (grade BETWEEN 1 AND 11),
    section VARCHAR(10) NOT NULL,
    family_id VARCHAR(32) NOT NULL,
    graduation_date VARCHAR(32)
);

CREATE TABLE IF NOT EXISTS public.teacher_details (
    id SERIAL PRIMARY KEY,
    user_id INTEGER NOT NULL UNIQUE REFERENCES public.users(id) ON DELETE CASCADE,
    taught_grade INTEGER NOT NULL CHECK (taught_grade BETWEEN 1 AND 11)
);

CREATE TABLE IF NOT EXISTS public.guardians (
    id SERIAL PRIMARY KEY,
    student_id INTEGER NOT NULL REFERENCES public.users(id) ON DELETE CASCADE,
    position INTEGER NOT NULL CHECK (position IN (1, 2)),
    name VARCHAR(255) NOT NULL,
    phone VARCHAR(64) NOT NULL,
    email VARCHAR(255)
);

CREATE TABLE IF NOT EXISTS public.attendance_records (
    id SERIAL PRIMARY KEY,
    event_type VARCHAR(32) NOT NULL,
    date VARCHAR(32) NOT NULL,
    time VARCHAR(32) NOT NULL,
    status VARCHAR(32),
    badge_uid VARCHAR(32) NOT NULL,
    user_id INTEGER REFERENCES public.users(id) ON DELETE SET NULL,
    name VARCHAR(255) NOT NULL,
    role VARCHAR(32) NOT NULL,
    grade INTEGER,
    section VARCHAR(10)
);

CREATE INDEX IF NOT EXISTS idx_users_badge_uid ON public.users (badge_uid);
CREATE INDEX IF NOT EXISTS idx_users_email_lower ON public.users (LOWER(email));
CREATE INDEX IF NOT EXISTS idx_guardians_email_lower ON public.guardians (LOWER(email));
CREATE INDEX IF NOT EXISTS idx_student_details_family_id ON public.student_details (family_id);
CREATE INDEX IF NOT EXISTS idx_student_details_grade ON public.student_details (grade);
CREATE INDEX IF NOT EXISTS idx_attendance_records_date ON public.attendance_records (date);
CREATE INDEX IF NOT EXISTS idx_attendance_records_badge_uid ON public.attendance_records (badge_uid);
CREATE INDEX IF NOT EXISTS idx_attendance_records_grade ON public.attendance_records (grade);

-- Deduplicate any pre-existing identical scan rows before creating the unique index
DELETE FROM public.attendance_records a
USING public.attendance_records b
WHERE a.id > b.id
  AND a.badge_uid = b.badge_uid
  AND a.date = b.date
  AND a.time = b.time
  AND a.event_type = b.event_type;

CREATE UNIQUE INDEX IF NOT EXISTS uq_attendance_records_scan
    ON public.attendance_records (badge_uid, date, time, event_type);

-- 2. Authorized Email Trigger on auth.users
CREATE OR REPLACE FUNCTION public.check_authorized_email()
RETURNS TRIGGER
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = public
AS $$
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM public.guardians WHERE LOWER(email) = LOWER(NEW.email)
        UNION
        SELECT 1 FROM public.users WHERE LOWER(email) = LOWER(NEW.email) AND role IN ('teacher', 'admin')
    ) THEN
        RAISE EXCEPTION 'Este correo no está registrado en el sistema escolar. Comuníquese con la administración.';
    END IF;
    RETURN NEW;
END;
$$;

DROP TRIGGER IF EXISTS enforce_authorized_email ON auth.users;
CREATE TRIGGER enforce_authorized_email
    BEFORE INSERT ON auth.users
    FOR EACH ROW
    EXECUTE FUNCTION public.check_authorized_email();

-- Ensure synced attendance_records automatically link to the matching public.users(id) by badge_uid
CREATE OR REPLACE FUNCTION public.resolve_attendance_user_id()
RETURNS TRIGGER
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = public
AS $$
DECLARE
    v_matched_id INTEGER;
BEGIN
    SELECT id INTO v_matched_id
    FROM public.users
    WHERE badge_uid = NEW.badge_uid
    LIMIT 1;

    IF v_matched_id IS NOT NULL THEN
        NEW.user_id := v_matched_id;
    ELSIF NEW.user_id IS NOT NULL AND NOT EXISTS (SELECT 1 FROM public.users WHERE id = NEW.user_id) THEN
        NEW.user_id := NULL;
    END IF;
    RETURN NEW;
END;
$$;

DROP TRIGGER IF EXISTS trg_resolve_attendance_user_id ON public.attendance_records;
CREATE TRIGGER trg_resolve_attendance_user_id
    BEFORE INSERT OR UPDATE ON public.attendance_records
    FOR EACH ROW
    EXECUTE FUNCTION public.resolve_attendance_user_id();

-- 3. Row-Level Security (RLS) Helper Functions
CREATE OR REPLACE FUNCTION public.get_auth_email()
RETURNS TEXT
LANGUAGE sql
STABLE
SECURITY DEFINER
SET search_path = public
AS $$
    SELECT LOWER(TRIM(COALESCE(
        NULLIF(current_setting('request.jwt.claim.email', true), ''),
        (NULLIF(current_setting('request.jwt.claims', true), '')::jsonb ->> 'email')
    )));
$$;

CREATE OR REPLACE FUNCTION public.get_auth_role()
RETURNS TEXT
LANGUAGE plpgsql
STABLE
SECURITY DEFINER
SET search_path = public
AS $$
DECLARE
    v_email TEXT;
    v_role TEXT;
BEGIN
    v_email := public.get_auth_email();
    IF v_email IS NULL OR v_email = '' THEN
        RETURN NULL;
    END IF;

    IF EXISTS (SELECT 1 FROM public.guardians WHERE LOWER(email) = v_email) THEN
        RETURN 'guardian';
    END IF;

    SELECT u.role INTO v_role
    FROM public.users u
    WHERE LOWER(u.email) = v_email AND u.role IN ('teacher', 'admin')
    LIMIT 1;

    RETURN v_role;
END;
$$;

CREATE OR REPLACE FUNCTION public.get_auth_family_id()
RETURNS TEXT
LANGUAGE plpgsql
STABLE
SECURITY DEFINER
SET search_path = public
AS $$
DECLARE
    v_email TEXT;
    v_family_id TEXT;
BEGIN
    v_email := public.get_auth_email();
    IF v_email IS NULL OR v_email = '' THEN
        RETURN NULL;
    END IF;

    SELECT COALESCE(sd.family_id, 'FAM-' || LPAD(g.student_id::text, 4, '0'))
    INTO v_family_id
    FROM public.guardians g
    LEFT JOIN public.student_details sd ON sd.user_id = g.student_id
    WHERE LOWER(g.email) = v_email
    LIMIT 1;

    RETURN v_family_id;
END;
$$;

CREATE OR REPLACE FUNCTION public.get_auth_teacher_grade()
RETURNS INTEGER
LANGUAGE plpgsql
STABLE
SECURITY DEFINER
SET search_path = public
AS $$
DECLARE
    v_email TEXT;
    v_grade INTEGER;
BEGIN
    v_email := public.get_auth_email();
    IF v_email IS NULL OR v_email = '' THEN
        RETURN NULL;
    END IF;

    SELECT td.taught_grade
    INTO v_grade
    FROM public.users u
    JOIN public.teacher_details td ON td.user_id = u.id
    WHERE LOWER(u.email) = v_email AND u.role = 'teacher'
    LIMIT 1;

    RETURN v_grade;
END;
$$;

-- 4. Authenticated Web Account & Scope Resolution RPC
CREATE OR REPLACE FUNCTION public.get_web_account()
RETURNS jsonb
LANGUAGE plpgsql
STABLE
SECURITY DEFINER
SET search_path = public
AS $$
DECLARE
    v_email TEXT;
    v_guardian RECORD;
    v_family_id TEXT;
    v_students jsonb;
    v_teacher RECORD;
    v_taught_grade INTEGER;
    v_admin RECORD;
BEGIN
    v_email := public.get_auth_email();

    IF v_email IS NULL OR v_email = '' THEN
        RAISE EXCEPTION 'Sesión no autenticada.';
    END IF;

    -- 1. Check Guardian
    SELECT g.id, g.student_id, g.name, g.phone, g.email
    INTO v_guardian
    FROM public.guardians g
    WHERE LOWER(g.email) = v_email
    LIMIT 1;

    IF FOUND THEN
        v_family_id := public.get_auth_family_id();

        SELECT COALESCE(jsonb_agg(
            jsonb_build_object(
                'id', u.id,
                'name', u.full_name,
                'badge_uid', u.badge_uid,
                'grade', sd.grade,
                'section', sd.section
            ) ORDER BY sd.grade ASC, u.full_name ASC
        ), '[]'::jsonb)
        INTO v_students
        FROM public.users u
        JOIN public.student_details sd ON sd.user_id = u.id
        WHERE sd.family_id = v_family_id AND u.is_active = TRUE;

        RETURN jsonb_build_object(
            'id', v_guardian.id,
            'email', v_email,
            'role', 'guardian',
            'name', v_guardian.name,
            'linked_entity_id', v_family_id,
            'details', jsonb_build_object(
                'family_id', v_family_id,
                'phone', v_guardian.phone,
                'students', v_students,
                'children', v_students
            )
        );
    END IF;

    -- 2. Check Teacher
    SELECT u.id, u.full_name, u.badge_uid, u.email
    INTO v_teacher
    FROM public.users u
    WHERE LOWER(u.email) = v_email AND u.role = 'teacher'
    LIMIT 1;

    IF FOUND THEN
        v_taught_grade := COALESCE(public.get_auth_teacher_grade(), 1);

        RETURN jsonb_build_object(
            'id', v_teacher.id,
            'email', v_email,
            'role', 'teacher',
            'name', v_teacher.full_name,
            'linked_entity_id', v_teacher.id::text,
            'details', jsonb_build_object(
                'taught_grade', v_taught_grade,
                'badge_uid', v_teacher.badge_uid
            )
        );
    END IF;

    -- 3. Check Admin
    SELECT u.id, u.full_name, u.badge_uid, u.email
    INTO v_admin
    FROM public.users u
    WHERE LOWER(u.email) = v_email AND u.role = 'admin'
    LIMIT 1;

    IF FOUND THEN
        RETURN jsonb_build_object(
            'id', v_admin.id,
            'email', v_email,
            'role', 'admin',
            'name', v_admin.full_name,
            'linked_entity_id', v_admin.id::text,
            'details', jsonb_build_object(
                'badge_uid', v_admin.badge_uid
            )
        );
    END IF;

    RAISE EXCEPTION 'Este correo no está registrado en el sistema escolar. Comuníquese con la administración.';
END;
$$;

CREATE OR REPLACE FUNCTION public.get_my_profile()
RETURNS jsonb
LANGUAGE sql
STABLE
SECURITY DEFINER
SET search_path = public
AS $$
    SELECT public.get_web_account();
$$;

-- 5. Enable Row-Level Security & Define Policies
ALTER TABLE public.users ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.student_details ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.teacher_details ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.guardians ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.attendance_records ENABLE ROW LEVEL SECURITY;

-- Drop existing policies idempotently
DROP POLICY IF EXISTS guardian_select_student_details ON public.student_details;
DROP POLICY IF EXISTS teacher_select_student_details ON public.student_details;
DROP POLICY IF EXISTS admin_select_student_details ON public.student_details;

DROP POLICY IF EXISTS guardian_select_users ON public.users;
DROP POLICY IF EXISTS teacher_select_users ON public.users;
DROP POLICY IF EXISTS admin_select_users ON public.users;

DROP POLICY IF EXISTS guardian_select_guardians ON public.guardians;
DROP POLICY IF EXISTS admin_select_guardians ON public.guardians;

DROP POLICY IF EXISTS teacher_select_teacher_details ON public.teacher_details;
DROP POLICY IF EXISTS admin_select_teacher_details ON public.teacher_details;

DROP POLICY IF EXISTS guardian_select_attendance_records ON public.attendance_records;
DROP POLICY IF EXISTS teacher_select_attendance_records ON public.attendance_records;
DROP POLICY IF EXISTS admin_select_attendance_records ON public.attendance_records;

-- Policies on student_details
CREATE POLICY guardian_select_student_details ON public.student_details
    FOR SELECT TO authenticated
    USING (public.get_auth_role() = 'guardian' AND family_id = public.get_auth_family_id());

CREATE POLICY teacher_select_student_details ON public.student_details
    FOR SELECT TO authenticated
    USING (public.get_auth_role() = 'teacher' AND grade = public.get_auth_teacher_grade());

CREATE POLICY admin_select_student_details ON public.student_details
    FOR SELECT TO authenticated
    USING (public.get_auth_role() = 'admin');

-- Policies on users
CREATE POLICY guardian_select_users ON public.users
    FOR SELECT TO authenticated
    USING (
        public.get_auth_role() = 'guardian'
        AND id IN (
            SELECT user_id FROM public.student_details WHERE family_id = public.get_auth_family_id()
        )
    );

CREATE POLICY teacher_select_users ON public.users
    FOR SELECT TO authenticated
    USING (
        public.get_auth_role() = 'teacher'
        AND (
            id IN (
                SELECT user_id FROM public.student_details WHERE grade = public.get_auth_teacher_grade()
            )
            OR LOWER(email) = public.get_auth_email()
        )
    );

CREATE POLICY admin_select_users ON public.users
    FOR SELECT TO authenticated
    USING (public.get_auth_role() = 'admin');

-- Policies on guardians
CREATE POLICY guardian_select_guardians ON public.guardians
    FOR SELECT TO authenticated
    USING (
        public.get_auth_role() = 'guardian'
        AND (
            LOWER(email) = public.get_auth_email()
            OR student_id IN (
                SELECT user_id FROM public.student_details WHERE family_id = public.get_auth_family_id()
            )
        )
    );

CREATE POLICY admin_select_guardians ON public.guardians
    FOR SELECT TO authenticated
    USING (public.get_auth_role() = 'admin');

-- Policies on teacher_details
CREATE POLICY teacher_select_teacher_details ON public.teacher_details
    FOR SELECT TO authenticated
    USING (public.get_auth_role() = 'teacher' AND taught_grade = public.get_auth_teacher_grade());

CREATE POLICY admin_select_teacher_details ON public.teacher_details
    FOR SELECT TO authenticated
    USING (public.get_auth_role() = 'admin');

-- Policies on attendance_records
CREATE POLICY guardian_select_attendance_records ON public.attendance_records
    FOR SELECT TO authenticated
    USING (
        public.get_auth_role() = 'guardian'
        AND (
            user_id IN (
                SELECT user_id FROM public.student_details WHERE family_id = public.get_auth_family_id()
            )
            OR badge_uid IN (
                SELECT u.badge_uid
                FROM public.users u
                JOIN public.student_details sd ON sd.user_id = u.id
                WHERE sd.family_id = public.get_auth_family_id()
            )
        )
    );

CREATE POLICY teacher_select_attendance_records ON public.attendance_records
    FOR SELECT TO authenticated
    USING (
        public.get_auth_role() = 'teacher'
        AND (
            grade = public.get_auth_teacher_grade()
            OR user_id IN (
                SELECT user_id FROM public.student_details WHERE grade = public.get_auth_teacher_grade()
            )
        )
    );

CREATE POLICY admin_select_attendance_records ON public.attendance_records
    FOR SELECT TO authenticated
    USING (public.get_auth_role() = 'admin');

-- Helper to resolve active school dates in a range (returns only date strings, no user data)
CREATE OR REPLACE FUNCTION public.get_school_dates(
    p_date_start TEXT DEFAULT NULL,
    p_date_end TEXT DEFAULT NULL
)
RETURNS TEXT[]
LANGUAGE sql
STABLE
SECURITY DEFINER
SET search_path = public
AS $$
    SELECT COALESCE(ARRAY_AGG(d ORDER BY d DESC), ARRAY[]::TEXT[])
    FROM (
        SELECT DISTINCT ar.date AS d
        FROM public.attendance_records ar
        WHERE (p_date_start IS NULL OR ar.date >= p_date_start)
          AND (p_date_end IS NULL OR ar.date <= p_date_end)
    ) sub;
$$;

-- 6. Year View Attendance & Punctuality Aggregation RPC (Respects RLS via SECURITY INVOKER)
CREATE OR REPLACE FUNCTION public.get_year_view_stats(
    p_date_start TEXT DEFAULT NULL,
    p_date_end TEXT DEFAULT NULL,
    p_student_id INTEGER DEFAULT NULL,
    p_grade INTEGER DEFAULT NULL,
    p_section TEXT DEFAULT NULL
)
RETURNS jsonb
LANGUAGE plpgsql
STABLE
SET search_path = public
AS $$
DECLARE
    v_role TEXT;
    v_family_id TEXT;
    v_teacher_grade INTEGER;
    v_school_dates TEXT[];
    v_total_school_days INTEGER := 0;
    v_student RECORD;
    v_date TEXT;
    v_checkin_time TEXT;
    v_checkin_status TEXT;
    v_checkout_time TEXT;
    v_day_status TEXT;
    v_present INTEGER;
    v_late INTEGER;
    v_absent INTEGER;
    v_punctuality NUMERIC(5,1);
    v_days jsonb;
    v_history jsonb;
    v_students jsonb := '[]'::jsonb;
    v_total_students INTEGER := 0;
    v_sum_present INTEGER := 0;
    v_sum_late INTEGER := 0;
    v_sum_absent INTEGER := 0;
    v_sum_punctuality NUMERIC := 0;
    v_avg_punctuality NUMERIC(5,1) := 100.0;
BEGIN
    v_role := public.get_auth_role();
    v_family_id := public.get_auth_family_id();
    v_teacher_grade := public.get_auth_teacher_grade();

    v_school_dates := public.get_school_dates(p_date_start, p_date_end);
    v_total_school_days := COALESCE(array_length(v_school_dates, 1), 0);

    FOR v_student IN
        SELECT u.id, u.full_name, u.badge_uid, sd.grade, sd.section, sd.family_id
        FROM public.users u
        JOIN public.student_details sd ON sd.user_id = u.id
        WHERE u.is_active = TRUE
          AND u.role = 'student'
          AND (p_student_id IS NULL OR u.id = p_student_id)
          AND (p_grade IS NULL OR sd.grade = p_grade)
          AND (
              p_section IS NULL
              OR UPPER(TRIM(p_section)) IN ('', 'ALL', 'TODAS')
              OR UPPER(sd.section) = UPPER(TRIM(p_section))
          )
        ORDER BY sd.grade ASC, sd.section ASC, u.full_name ASC
    LOOP
        v_present := 0;
        v_late := 0;
        v_days := '{}'::jsonb;
        v_history := '[]'::jsonb;

        IF v_total_school_days > 0 THEN
            FOREACH v_date IN ARRAY v_school_dates
            LOOP
                v_checkin_time := NULL;
                v_checkin_status := NULL;
                v_checkout_time := NULL;

                SELECT ar.time, ar.status
                INTO v_checkin_time, v_checkin_status
                FROM public.attendance_records ar
                WHERE (ar.user_id = v_student.id OR ar.badge_uid = v_student.badge_uid)
                  AND ar.date = v_date
                  AND ar.event_type = 'check_in'
                ORDER BY ar.time ASC
                LIMIT 1;

                SELECT ar.time
                INTO v_checkout_time
                FROM public.attendance_records ar
                WHERE (ar.user_id = v_student.id OR ar.badge_uid = v_student.badge_uid)
                  AND ar.date = v_date
                  AND ar.event_type = 'check_out'
                ORDER BY ar.time DESC
                LIMIT 1;

                IF v_checkin_time IS NOT NULL THEN
                    v_present := v_present + 1;
                    IF v_checkin_status = 'late' THEN
                        v_late := v_late + 1;
                        v_days := v_days || jsonb_build_object(v_date, 'T');
                    ELSE
                        v_days := v_days || jsonb_build_object(v_date, 'P');
                    END IF;

                    IF v_checkout_time IS NOT NULL THEN
                        v_day_status := 'departed';
                    ELSIF v_checkin_status = 'late' THEN
                        v_day_status := 'late';
                    ELSE
                        v_day_status := 'on_time';
                    END IF;

                    v_history := v_history || jsonb_build_array(
                        jsonb_build_object(
                            'date', v_date,
                            'check_in_time', v_checkin_time,
                            'check_out_time', v_checkout_time,
                            'checkin_status', COALESCE(v_checkin_status, 'on_time'),
                            'entry_time', v_checkin_time,
                            'exit_time', v_checkout_time,
                            'status', v_day_status
                        )
                    );
                ELSE
                    v_days := v_days || jsonb_build_object(v_date, 'A');
                    v_history := v_history || jsonb_build_array(
                        jsonb_build_object(
                            'date', v_date,
                            'check_in_time', NULL,
                            'check_out_time', NULL,
                            'checkin_status', 'absent',
                            'entry_time', NULL,
                            'exit_time', NULL,
                            'status', 'absent'
                        )
                    );
                END IF;
            END LOOP;
        END IF;

        v_absent := GREATEST(0, v_total_school_days - v_present);
        IF v_present > 0 THEN
            v_punctuality := ROUND(((v_present - v_late)::numeric / v_present::numeric) * 100.0, 1);
        ELSE
            v_punctuality := 100.0;
        END IF;

        v_students := v_students || jsonb_build_array(
            jsonb_build_object(
                'student_id', v_student.id,
                'name', v_student.full_name,
                'badge_uid', v_student.badge_uid,
                'grade', v_student.grade,
                'section', v_student.section,
                'family_id', v_student.family_id,
                'present_days', v_present,
                'late_days', v_late,
                'absent_days', v_absent,
                'punctuality_rate', v_punctuality::float8,
                'metrics', jsonb_build_object(
                    'present_days', v_present,
                    'late_days', v_late,
                    'absent_days', v_absent,
                    'punctuality_rate', v_punctuality::float8
                ),
                'days', v_days,
                'history', v_history
            )
        );

        v_total_students := v_total_students + 1;
        v_sum_present := v_sum_present + v_present;
        v_sum_late := v_sum_late + v_late;
        v_sum_absent := v_sum_absent + v_absent;
        v_sum_punctuality := v_sum_punctuality + v_punctuality;
    END LOOP;

    IF v_total_students > 0 THEN
        v_avg_punctuality := ROUND(v_sum_punctuality / v_total_students, 1);
    END IF;

    RETURN jsonb_build_object(
        'family_id', v_family_id,
        'grade', COALESCE(v_teacher_grade, p_grade),
        'total_school_days', v_total_school_days,
        'total_students', v_total_students,
        'school_dates', to_jsonb(v_school_dates),
        'summary', jsonb_build_object(
            'total_students', v_total_students,
            'total_present_days', v_sum_present,
            'total_late_days', v_sum_late,
            'total_absent_days', v_sum_absent,
            'average_punctuality', v_avg_punctuality::float8
        ),
        'students', v_students
    );
END;
$$;

-- Table & Function Grants
GRANT USAGE ON SCHEMA public TO anon, authenticated, service_role;
GRANT SELECT ON public.users, public.student_details, public.teacher_details, public.guardians, public.attendance_records TO authenticated;
GRANT ALL ON ALL TABLES IN SCHEMA public TO service_role;
GRANT USAGE, SELECT ON ALL SEQUENCES IN SCHEMA public TO service_role;
GRANT EXECUTE ON FUNCTION public.get_web_account() TO anon, authenticated, service_role;
GRANT EXECUTE ON FUNCTION public.get_my_profile() TO anon, authenticated, service_role;
GRANT EXECUTE ON FUNCTION public.get_auth_email() TO anon, authenticated, service_role;
GRANT EXECUTE ON FUNCTION public.get_auth_role() TO anon, authenticated, service_role;
GRANT EXECUTE ON FUNCTION public.get_auth_family_id() TO anon, authenticated, service_role;
GRANT EXECUTE ON FUNCTION public.get_auth_teacher_grade() TO anon, authenticated, service_role;
GRANT EXECUTE ON FUNCTION public.get_school_dates(TEXT, TEXT) TO anon, authenticated, service_role;
GRANT EXECUTE ON FUNCTION public.get_year_view_stats(TEXT, TEXT, INTEGER, INTEGER, TEXT) TO anon, authenticated, service_role;
