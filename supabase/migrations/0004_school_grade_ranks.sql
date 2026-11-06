-- Quickpass Supabase migration 0004: Grades are ranks into the School's own list.
-- A Grade is stored as its 1-based rank in school_settings.grades, so a School
-- may have any number of Grades; the database no longer stops at 11. Renaming a
-- Grade changes only the label in school_settings, never these columns.

ALTER TABLE public.student_details DROP CONSTRAINT IF EXISTS student_details_grade_check;
ALTER TABLE public.student_details ADD CONSTRAINT student_details_grade_check CHECK (grade >= 1);

ALTER TABLE public.teacher_details DROP CONSTRAINT IF EXISTS teacher_details_taught_grade_check;
ALTER TABLE public.teacher_details ADD CONSTRAINT teacher_details_taught_grade_check CHECK (taught_grade >= 1);

COMMENT ON COLUMN public.student_details.grade IS
    'Grade rank (1-based) in school_settings.grades; the label shown comes from that list.';
COMMENT ON COLUMN public.teacher_details.taught_grade IS
    'Rank (1-based) in school_settings.grades of the one Grade this Teacher teaches.';
COMMENT ON COLUMN public.attendance_records.grade IS
    'Grade rank the person held at the time of the scan.';
