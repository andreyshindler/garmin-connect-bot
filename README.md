# garmin-connect-bot

סקריפט שמסנכרן נתונים מ-Garmin Connect לקובץ SQLite מקומי.

- מתחבר לגרמין ושומר טוקנים (ב-`data/.garminconnect`), כך שהסיסמה נדרשת רק בהרצה הראשונה. אם מופעל אצלך MFA, הוא ישאל קוד.
- שומר פעילויות ב-SQLite (`garmin.db`): מרחק, משך, גובה, דופק, וואטים (avg/NP/max), קלוריות, יחד עם ה-JSON המלא.
- שומר נתונים יומיים: דופק מנוחה, צעדים, סטרס, Body Battery, שינה וציון שינה.
- רץ אינקרמנטלית עם חפיפה של יומיים, כדי לתפוס סנכרונים של השעון שמגיעים באיחור.
- עם `--fit` הוא מוריד גם את קבצי ה-FIT המקוריים (לתיקייה `fit/`), שימושי לניתוח כוח.
- רץ בתוך Docker ומסנכרן אוטומטית כל שעה.

## התקנה על ה-VPS (Docker)

נדרשים Docker ו-Docker Compose. אם הם לא מותקנים:

```bash
curl -fsSL https://get.docker.com | sudo sh
```

```bash
git clone https://github.com/andreyshindler/garmin-connect-bot.git ~/garmin-connect-bot
cd ~/garmin-connect-bot
docker compose build
```

### הרצה ראשונה (אינטראקטיבית)

```bash
docker compose run --rm -it garmin-sync "python /app/garmin_sync.py --fit"
```

הסקריפט ישאל אימייל, סיסמה וקוד MFA (אם מופעל), וישמור טוקנים ב-`data/.garminconnect`.
בהרצה הראשונה הוא מושך 30 ימים אחורה. להיסטוריה ארוכה יותר:

```bash
docker compose run --rm -it garmin-sync "python /app/garmin_sync.py --since 2024-01-01 --fit"
```

### הרצה ברקע

```bash
docker compose up -d
docker compose logs -f      # צפייה בלוג
```

הקונטיינר מסנכרן כל שעה ועולה מחדש אוטומטית אחרי ריבוט. אפשר לשנות את התדירות (בשניות) ואת אזור הזמן בקובץ `.env` ליד `docker-compose.yml`:

```env
SYNC_INTERVAL=1800
TZ=Asia/Jerusalem
```

כל הנתונים נשמרים בתיקייה `data/` על ה-VPS: `garmin.db`, קבצי FIT ב-`fit/`, והטוקנים ב-`.garminconnect/`.
אם הטוקנים פגו, יופיע בלוג `Authentication failed`; צריך להריץ שוב את ההרצה הראשונה ואז `docker compose restart`.

### עדכון

```bash
git pull && docker compose up -d --build
```

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
cd ~/garmin-connect-bot/data
sqlite3 garmin.db "SELECT date(start_time), activity_type, round(distance_m/1000,1) km, avg_power, norm_power FROM activities ORDER BY start_time DESC LIMIT 10;"
sqlite3 garmin.db "SELECT day, resting_hr, steps, sleep_score, body_battery_high FROM daily ORDER BY day DESC LIMIT 14;"
```
