"""Email body builders for the OAuth onboarding flow."""


def build_share_code_email(
	*,
	site: str,
	provider: str,
	verification_uri: str,
	user_code: str,
	minutes_left: int,
	sender_name: str,
) -> dict:
	"""Return ``{subject, body}`` for the 'Send code to colleague' affordance."""
	subject = f"Help me finish setting up Jarvis ({site})"
	body = (
		f"Hi,\n\n"
		f"I'm setting up Jarvis at {site}. To finish, please:\n\n"
		f"  1. Open: {verification_uri}\n"
		f"  2. Sign in with the {provider} account you'd like Jarvis to use\n"
		f"  3. Type the code: {user_code}\n"
		f"  4. Click \"Authorize\"\n\n"
		f"The code expires in {minutes_left} minutes.\n\n"
		f"Jarvis will use your subscription for AI calls — no extra cost, "
		f"no API key needed.\n\n"
		f"Thanks!\n"
		f"{sender_name}\n"
	)
	return {"subject": subject, "body": body}
