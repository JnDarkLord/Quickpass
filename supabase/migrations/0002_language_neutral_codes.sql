-- Quickpass Supabase migration 0002: language-neutral values.
-- Errors raise a machine-readable code as their message, with English text in
-- DETAIL for maintainers; the portal turns the code into the School's language.
-- The Year View Section filter recognizes only the neutral ALL value (or no
-- value) as "every Section"; any other value, such as TODAS, is a Section name.

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
        RAISE EXCEPTION 'ERR_UNAUTHORIZED_EMAIL'
            USING DETAIL = 'This email is not an Authorized Email of the School. Contact the school administration.';
    END IF;
    RETURN NEW;
END;
$$;

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
        RAISE EXCEPTION 'ERR_NOT_AUTHENTICATED'
            USING DETAIL = 'There is no signed-in session.';
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

    RAISE EXCEPTION 'ERR_UNAUTHORIZED_EMAIL'
        USING DETAIL = 'This email is not an Authorized Email of the School. Contact the school administration.';
END;
$$;

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
              OR UPPER(TRIM(p_section)) IN ('', 'ALL')
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

GRANT EXECUTE ON FUNCTION public.get_web_account() TO anon, authenticated, service_role;
GRANT EXECUTE ON FUNCTION public.get_year_view_stats(TEXT, TEXT, INTEGER, INTEGER, TEXT) TO anon, authenticated, service_role;
