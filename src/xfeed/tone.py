"""Tone analysis for reply notifications using Claude Haiku."""

import json
import anthropic

from xfeed.config import get_api_key
from xfeed.models import Notification, NotificationType


def analyze_reply_tones(notifications: list[Notification]) -> list[Notification]:
    """
    Analyze the tone of reply notifications using Claude Haiku.

    Returns the same notifications with reply_tone field populated
    with a short descriptive tone (e.g., "curious", "supportive", "hostile").
    """
    # Filter to just replies with content
    replies_with_content = [
        (i, n) for i, n in enumerate(notifications)
        if n.type == NotificationType.REPLY and n.reply_content
    ]

    if not replies_with_content:
        return notifications

    # Build the prompt with context
    replies_text = "\n".join([
        f'{i}: Original: "{n.reply_to_content or "unknown"}"\n   Reply: "{n.reply_content}"'
        for i, n in replies_with_content
    ])

    prompt = f"""For each reply, describe its tone in ONE word considering the context of what they're replying to. Be creative and precise - capture the vibe.

{replies_text}

Respond with JSON mapping index to tone word:
{{"0": "curious", "1": "snarky", ...}}

JSON only:"""

    try:
        api_key = get_api_key()
        if not api_key:
            return notifications

        client = anthropic.Anthropic(api_key=api_key)

        response = client.messages.create(
            model="claude-3-haiku-20240307",
            max_tokens=500,
            messages=[{"role": "user", "content": prompt}]
        )

        # Parse the response
        response_text = response.content[0].text.strip()

        # Extract JSON from response (handle markdown code blocks)
        if "```" in response_text:
            import re
            json_match = re.search(r'```(?:json)?\s*([\s\S]*?)\s*```', response_text)
            if json_match:
                response_text = json_match.group(1)

        tone_map = json.loads(response_text)

        # Apply tones to notifications
        for idx_str, tone in tone_map.items():
            idx = int(idx_str)
            # Find the notification at this index in our filtered list
            for orig_idx, notif in replies_with_content:
                if orig_idx == idx:
                    notif.reply_tone = tone.lower()
                    break

    except Exception:
        # If analysis fails, leave tones as None
        pass

    return notifications
