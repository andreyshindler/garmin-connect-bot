# garmin-connect-bot

סקריפט שמסנכרן נתונים מ-Garmin Connect לקובץ SQLite מקומי.

- מתחבר לגרמין ושומר טוקנים ב-`~/.garminconnect`, כך שהסיסמה נדרשת רק בהרצה הראשונה. אם מופעל אצלך MFA, הוא ישאל קוד.
- שומר פעילויות ב-SQLite (`garmin.db`): מרחק, משך, גובה, דופק, וואטים (avg/NP/max), קלוריות, יחד עם ה-JSON המלא.
- שומר נתונים יומיים: דופק מנוחה, צעדים, סטרס, Body Battery, שינה וציון שינה.
- רץ אינקרמנטלית עם חפיפה של יומיים, כדי לתפוס סנכרונים של השעון שמגיעים באיחור.
- עם `--fit` הוא מוריד גם את קבצי ה-FIT המקוריים (לתיקייה `fit/`), שימושי לניתוח כוח.

## התקנה על ה-VPS

נדרש Python 3.10 ומעלה.

```bash
sudo apt update && sudo apt install -y python3 python3-venv git sqlite3
git clone https://github.com/andreyshindler/garmin-connect-bot.git ~/garmin-connect-bot
cd ~/garmin-connect-bot
python3 -m venv .venv
.venv/bin/pip install -r requirements.txt
```

### הרצה ראשונה (אינטראקטיבית)

```bash
cd ~/garmin-connect-bot
.venv/bin/python garmin_sync.py --fit
```

הסקריפט ישאל אימייל, סיסמה וקוד MFA (אם מופעל), וישמור טוקנים ב-`~/.garminconnect`.
בהרצה הראשונה הוא מושך 30 ימים אחורה. להיסטוריה ארוכה יותר:

```bash
.venv/bin/python garmin_sync.py --since 2024-01-01 --fit
```

### הרצה אוטומטית (cron)

`crontab -e` והוספת השורה (כל שעה, בדקה 17):

```cron
17 * * * * cd $HOME/garmin-connect-bot && .venv/bin/python garmin_sync.py --fit >> sync.log 2>&1
```

ה-cron רץ בתור אותו משתמש, אז הוא משתמש באותם טוקנים. אם הטוקנים פגו, הריצה תיכשל עם הודעה ב-`sync.log`; צריך פשוט להריץ שוב ידנית פעם אחת.

## אפשרויות

| דגל | משמעות |
|---|---|
| `--db PATH` | נתיב לקובץ ה-SQLite (ברירת מחדל `garmin.db`) |
| `--fit` | הורדת קבצי FIT מקוריים |
| `--fit-dir DIR` | תיקיית ה-FIT (ברירת מחדל `fit/`) |
| `--days N` | סנכרון N ימים אחרונים, בלי קשר למצב השמור |
| `--since YYYY-MM-DD` | סנכרון מתאריך מסוים |
| `-v` | לוג מפורט |

משתני סביבה: `GARMINTOKENS` (מיקום הטוקנים), `GARMIN_EMAIL` / `GARMIN_PASSWORD` (התחברות בלי שאלות).

## דוגמאות שאילתה

```bash
sqlite3 garmin.db "SELECT date(start_time), activity_type, round(distance_m/1000,1) km, avg_power, norm_power FROM activities ORDER BY start_time DESC LIMIT 10;"
sqlite3 garmin.db "SELECT day, resting_hr, steps, sleep_score, body_battery_high FROM daily ORDER BY day DESC LIMIT 14;"
```
