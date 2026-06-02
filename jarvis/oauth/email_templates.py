"""Email body builders for the OAuth onboarding flow (REV-3)."""


def build_share_paste_signin_email(
	*,
	sender_name: str,
	company: str,
	provider: str,
	authorize_url: str,
	bench_url: str,
	minutes_left: int,
) -> dict:
	"""Email body for the 'Send sign-in to a colleague' affordance."""
	subject = f"Help me finish setting up Jarvis for {company} ({provider})"
	body = (
		f"Hi,\n\n"
		f"{sender_name} is setting up Jarvis for {company} and asked you "
		f"to sign in with your {provider} subscription.\n\n"
		f"Step 1 — Open this link and sign in with your {provider} account:\n"
		f"  {authorize_url}\n\n"
		f"Step 2 — After clicking Authorize, your browser will show a\n"
		f"\"Can't reach this site\" page. That's expected. Copy the URL\n"
		f"from your browser's address bar and reply to this email with\n"
		f"that URL, or paste it into:\n"
		f"  {bench_url}/jarvis-account\n\n"
		f"The sign-in link is valid for {minutes_left} minutes.\n\n"
		f"If you didn't expect this email, you can ignore it.\n"
	)
	return {"subject": subject, "body": body}
