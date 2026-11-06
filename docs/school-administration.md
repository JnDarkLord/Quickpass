# School Administration

A guide for the School's Admins to running Quickpass day to day: Badges, the Door Gate, attendance searches and reports, the School Settings, and the end-of-year Grade Promotion.

It assumes Quickpass is installed and the setup wizard is done ([Desktop Setup](desktop-setup.md)).

## The window

The sidebar has three views:

- **Search and Reports:** past attendance, and the Excel reports.
- **Badge Management:** the Badge Directory, where Badges are registered, edited, and deleted, plus statistics, wipes, and the Grade Promotion.
- **School Settings:** the School's own policies.

**Open Live Access** opens the entrance window. It shows each tap at the Door Gate in the Live Access Feed. Its buttons are **Manual Unlock**, which opens the Door Gate for someone without a Badge, **Register Visitor**, and **Full Screen** (F11), for a screen facing the entrance.

## Admin Approval

Some changes need **Admin Approval**: an Admin taps their Badge on the reader, or types the **Admin Secret Key** instead. Quickpass asks for it to:

- edit a Badge,
- delete a Badge,
- run the Grade Promotion,
- save the School Settings.

Adding another Admin always needs an Admin to tap their Badge; the Admin Secret Key can't approve it. Registering the School's first Admin needs no approval, and neither does registering any other Badge or a Visitor.

The Admin Secret Key is chosen in the setup wizard and changed in School Settings. It exists so the School can still approve changes if its Admin's Badge is lost, so keep it somewhere safe.

## Badges

Students, Teachers, and Admins each have a Badge: a card, keyfob, or sticker with a unique Badge UID. Visitors can be given a temporary one. A person's **Role** is Student, Teacher, Admin, or Visitor.

### Registering a Badge

1. In **Badge Management**, click **Register Badge**.
2. Tap the new Badge on the reader. Quickpass shows its Badge UID, and tells you if it already belongs to someone.
3. Choose the Role and type the full name.
   - **Student:** choose their Grade and Section, and add up to two Guardians, each with a name and a WhatsApp phone number, and optionally an email. A Guardian's email is their Authorized Email for the web portal. Quickpass suggests a new **Family Code** (`FAM-0001`, `FAM-0002`, ...). If a Guardian's phone already belongs to a sibling's family, it links the Student to that family instead.
   - **Teacher:** choose the Grade they teach.
4. Click **Save and Register**.

Register the School's first Admin right after setup, so that later changes can be approved with their Badge.

### Editing and deleting

- **Edit** changes a person's name, Grade, Section, and Guardians. Tapping another Badge while editing gives the person that Badge's UID instead. A person's Role can't be changed.
- **Delete** removes a Badge and its details for good.
- The filter box finds people by name, Grade, Role, or Badge UID.
- **Statistics** shows how many people are registered, by Role and by Grade, and the Check-ins of recent days.

### Visitors

In the Live Access window, click **Register Visitor**, type the visitor's name and ID document, and optionally tap a temporary Badge to give them. Registering the visit opens the Door Gate.

### Web portal access

People sign in to the web portal with an **Authorized Email**:

- Guardians use the email typed for them when their Student's Badge was registered or edited.
- Teachers and Admins use the email in their row of Supabase's `users` table. The desktop window has no email field for them yet; [Web Portal Setup](web-portal-setup.md#who-can-sign-in) explains how to add it.

## At the Door Gate

![Door Gate Badge Tap and Attendance Decision Flow](images/badge-tap-workflow.svg)

When a person taps their Badge:

- The **first tap of the day** is their **Check-in**. The Door Gate opens, and the Check-in is **On Time** or **Late**, depending on the Late Threshold.
- A tap before the **wait between Check-in and Check-out** has passed is a **Repeat Scan**: the Door Gate opens, and nothing is recorded.
- The first tap after the wait is their **Check-out**. A person has at most one Check-out a day, and later taps are Repeat Scans.
- A **Graduate's** Badge, or an inactive person's, is refused.
- An **unregistered Badge** is refused and recorded as a security incident. If `ADMIN_ALERT_PHONE` is set, the first tap of each unregistered Badge on a day sends an alert.

If text messages are set up, a Student's Guardians get one at the Check-in, saying whether the Student was on time, and one at the Check-out.

## School Settings

The **School Settings** view holds the School's policies. Saving needs Admin Approval. With Cloud Sync, the changes reach Supabase, the other stations, and the web portal.

- **School Language:** Spanish or English. The window, the Door Gate's LCD, the reports, the text messages, and the web portal all switch to it. Names and other text the School typed in stay as typed.
- **Grades (in order):** the School's Grades from first to last. Double-click a Grade to rename it; its Students and Teachers keep it under the new name. New Grades go at the end, and only the last one can be removed. A Grade that still has active Students or Teachers can't be removed. The last Grade is the one that graduates at the Grade Promotion.
- **Sections:** double-click a Section to rename it; its Students keep it under the new name, and past scans keep the name it had then. You can also add and remove Sections. A Section name has at most 10 characters and can't be `ALL`. A Section that still has active Students can't be removed.
- **Weekdays with Classes** and **Holidays and Breaks:** together they decide the **School Days**. A holiday is not a School Day, so nobody is marked absent on it. Add the year's holidays here; the setup wizard doesn't ask for them.
- **Late Threshold:** a Check-in after this time is Late.
- **Wait between Check-in and Check-out:** in seconds. A tap inside the wait is a Repeat Scan. The default is 300 seconds, 5 minutes.
- **Admin Secret Key:** type a new key twice to change it, or leave it blank to keep the current one. It needs at least 8 characters.

## Searching attendance and exporting reports

The **Search and Reports** view searches past attendance and saves official Excel workbooks (`.xlsx`). Choose a search type, set its date or dates and filters, and click **Export to Excel**.

| Search type | Excel report |
|:---|:---|
| Attendance by Day | E2, the whole School on a date, or E3, one Grade, or one Grade and Section |
| History by Student or Person | E1, one person's full history |
| Date Range / Attendance Matrix | E4, every Grade, E5, one Grade, or E6, one Grade and Section, across a date range |
| General Check-in and Check-out Log | The log as shown |
| Teachers, Admins or Visitors by Day | E7, one Role on a date |
| Teachers, Admins or Visitors over a Date Range | E8, one Role's Check-in times across a date range |

- **Scan Badge** finds a person by tapping their Badge on the reader.
- The text filter also accepts a Family Code, such as `FAM-0001`.
- **Absences** count only on School Days. A date range counts only the School Days from the first to the last date with scans on record, as the web portal's Year View does, so the days before Quickpass started and the days still to come add no Absences.
- Reports are saved in the `REPORTS_DIR` folder (`Reports/` by default). **Open Reports Folder** opens it.

Searches and reports read the attendance history from Supabase when the station has a `DATABASE_URL`. Without one, they read the station's local database. With Cloud Sync on, that database keeps only today's scans and the ones not yet sent.

## The end-of-year Grade Promotion

Run it once a year, after the last School Day and before the new year starts:

1. In **Badge Management**, click **Promote (+1)** and approve it.
2. Quickpass shows how many Students move up one Grade and how many Students in the last Grade graduate. Confirm with **Yes, Promote**.

Every active Student moves up one Grade, and the Students in the last Grade become **Graduates**. Graduates keep their history, but their Badges no longer open the Door Gate. Teachers keep the Grade they teach.

There's no undo, and Quickpass doesn't save a backup first. Copy the station's database file (`DATABASE_PATH`) before you start.

## Wipes and backups

**Wipe Every Badge** deletes every Badge and its details, Guardians included, and keeps the attendance history. **Wipe Attendance History** deletes this station's Check-ins, Check-outs, and security incidents, and keeps every Badge. It doesn't delete what Cloud Sync has already sent to Supabase.

Both ask for the `WIPE_PASSWORD` from `.env` and for the confirmation word, `DELETE` in English or `ELIMINAR` in Spanish. Without a `WIPE_PASSWORD`, wipes are refused. Before wiping, Quickpass saves a backup of the station's database in the `backups/` folder next to it.

Copy the station's database file regularly too. With Cloud Sync, Supabase holds a second copy of the Badges and the attendance.
