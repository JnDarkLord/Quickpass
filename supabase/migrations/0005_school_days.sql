-- Quickpass Supabase migration 0005: School Days.
-- A School Day is one of the School's active weekdays that is not one of its
-- holidays (school_settings). The Year View now takes its days from that
-- calendar instead of from the dates that happen to have scans: adding a
-- holiday removes that day's Absences at once, a weekend scan never adds a
-- day, and a School Day nobody scanned on still counts every Student absent.
-- School Days are only counted between the first and the last date with scans
-- on record: before the first, Quickpass was not running yet; after the last,
-- Cloud Sync may not have uploaded the day's scans yet.

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
    WITH recorded AS (
        SELECT MIN(ar.date)::DATE AS first_day, MAX(ar.date)::DATE AS last_day
        FROM public.attendance_records ar
    ),
    calendar AS (
        -- Monday to Friday without holidays until the School saves its settings
        SELECT
            COALESCE(s.active_weekdays, ARRAY[0, 1, 2, 3, 4]::SMALLINT[]) AS active_weekdays,
            COALESCE(s.holidays, '[]'::JSONB) AS holidays
        FROM (SELECT 1) AS one
        LEFT JOIN public.school_settings s ON s.id = 1
    )
    SELECT COALESCE(ARRAY_AGG(to_char(g.day, 'YYYY-MM-DD') ORDER BY g.day DESC), ARRAY[]::TEXT[])
    FROM recorded
    CROSS JOIN calendar
    CROSS JOIN LATERAL generate_series(
        GREATEST(p_date_start::DATE, recorded.first_day)::TIMESTAMP,
        LEAST(p_date_end::DATE, recorded.last_day)::TIMESTAMP,
        INTERVAL '1 day'
    ) AS g(day)
    WHERE recorded.first_day IS NOT NULL
      AND (EXTRACT(ISODOW FROM g.day)::SMALLINT - 1) = ANY (calendar.active_weekdays)
      AND NOT calendar.holidays @> jsonb_build_array(to_char(g.day, 'YYYY-MM-DD'));
$$;

COMMENT ON FUNCTION public.get_school_dates(TEXT, TEXT) IS
    'School Days (YYYY-MM-DD, newest first) in the range, within the dates that have scans on record.';

GRANT EXECUTE ON FUNCTION public.get_school_dates(TEXT, TEXT) TO anon, authenticated, service_role;
