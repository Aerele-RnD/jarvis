"""Email body builders for the OAuth onboarding flow."""


def build_share_signin_email(
	*,
	sender_name: str,
	company: str,
	provider: str,
	one_liner: str,
	minutes_left: int,
) -> dict:
	"""Email body for the 'Send sign-in to a colleague' affordance."""
	subject = f"Help me finish setting up Jarvis for {company} ({provider})"
	body = (
		f"Hi,\n\n"
		f"{sender_name} is setting up Jarvis for {company} and asked you "
		f"to sign in with your {provider} subscription.\n\n"
		f"1. Open Terminal (or PowerShell on Windows) on your computer.\n"
		f"2. Paste this command and press Enter:\n\n"
		f"   {one_liner}\n\n"
		f"3. Sign in to {provider} in the browser window that opens.\n\n"
		f"The script sends your sign-in result back to Jarvis automatically.\n"
		f"Link valid for {minutes_left} minutes.\n\n"
		f"If you didn't expect this email, you can ignore it.\n"
	)
	return {"subject": subject, "body": body}
