# Squishy alerts

Checks Buyee every ~10 minutes (JDirectItems Auction, JDirectItems Fleamarket, Mercari, Rakuma, PayPay Flea Market) for the searches in `searches.txt` and emails you new listings.

## Setup (one time, ~15 min)

1. **Gmail app password**: turn on 2-step verification on your Google account, go to https://myaccount.google.com/apppasswords, create one, copy the 16-character password.
2. **Create a PUBLIC GitHub repo** and upload everything in this folder (keep the `.github/workflows/check.yml` path). It needs to be public: private repos only get 2,000 free Actions minutes a month, which isn't enough for 10-minute checks. Public means your search list and `seen.json` are visible to anyone. Your Gmail password is not, since it lives in secrets.
3. **Add secrets**: repo > Settings > Secrets and variables > Actions > New repository secret:
   - `GMAIL_USER` = your Gmail address
   - `GMAIL_APP_PASSWORD` = the 16-character password
   - `EMAIL_TO` = where alerts should go (can be the same address)
4. **Dry run**: Actions tab > check-listings > Run workflow, set `dry_run` to `true`. Open the log. Each line shows `marketplace | search: N items`. If a marketplace shows 0 everywhere, the log also prints a `[diag]` line with the item-style links it did find on the page.
5. **Real first run**: run it again with `dry_run` false. It silently records everything currently listed (no email). From then on you only get emailed about new listings.

## If a marketplace shows 0 items

The search URLs and link patterns in `MARKETPLACES` (top of `check.py`) are untested guesses, especially the two JDirectItems ones. Fix the URL by copying a real search URL from your browser and swapping the keyword for `{q}`. Fix the pattern using the `[diag]` links from the log. If you paste that log to me I can fix it for you.

If the pages load results with JavaScript, or Buyee blocks GitHub's servers, plain requests won't work. The script emails you if a marketplace returns nothing for 6 runs in a row (about an hour).

## Notes

- GitHub pauses scheduled workflows in a repo after ~60 days without activity. If alerts stop, open the Actions tab and re-enable the workflow.
- Two brand spellings are guesses, so `searches.txt` tries several: Aoyama Tokyo and Creamiicandy.
- Every extra line in `searches.txt` adds requests to every run. If you get blocked, remove lines or lower `WORKERS` in `check.py`.
- Automated access may go against Buyee's terms. Keep it to personal use.
