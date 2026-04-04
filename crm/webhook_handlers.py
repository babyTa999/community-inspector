"""Webhook handlers for n8n automation integration."""
from __future__ import annotations

import os
from typing import Any

import httpx


class WebhookClient:
    """Client for sending webhook notifications to n8n."""

    def __init__(self):
        """Initialize webhook client with URLs from environment."""
        self.new_issue_url = os.getenv("N8N_WEBHOOK_URL_NEW_ISSUE")
        self.high_priority_url = os.getenv("N8N_WEBHOOK_URL_HIGH_PRIORITY")
        self.feishu_webhook = os.getenv("FEISHU_WEBHOOK_URL")
        self.timeout = 10.0

    async def _send_webhook(
        self,
        url: str | None,
        payload: dict[str, Any],
    ) -> bool:
        """Send webhook payload to URL.

        Args:
            url: Webhook URL
            payload: Data to send

        Returns:
            True if successful
        """
        if not url:
            return False

        try:
            async with httpx.AsyncClient(timeout=self.timeout) as client:
                response = await client.post(
                    url,
                    json=payload,
                    headers={"Content-Type": "application/json"},
                )
                return response.status_code < 400
        except Exception as e:
            print(f"Webhook error: {e}")
            return False

    async def notify_new_issue(
        self,
        entry_id: str,
        title: str,
        type_tag: str,
        status_tag: str,
        feature_module: str | None,
        user_name: str | None,
        source_type: str | None,
        source_url: str | None,
        priority: str = "中",
    ) -> bool:
        """Notify n8n about a new issue.

        Args:
            entry_id: Entry ID
            title: Issue title
            type_tag: Type tag (R/Q/S/Tips)
            status_tag: Status tag
            feature_module: Feature module
            user_name: User name
            source_type: Source type (Discord, Reddit, etc.)
            source_url: Source URL
            priority: Priority level

        Returns:
            True if webhook sent successfully
        """
        payload = {
            "event": "new_issue",
            "entry_id": entry_id,
            "title": title,
            "type_tag": type_tag,
            "status_tag": status_tag,
            "feature_module": feature_module,
            "user_name": user_name,
            "source_type": source_type,
            "source_url": source_url,
            "priority": priority,
            "crm_url": f"/entries/{entry_id}",
        }

        return await self._send_webhook(self.new_issue_url, payload)

    async def notify_high_priority(
        self,
        entry_id: str,
        title: str,
        type_tag: str,
        status_tag: str,
        feature_module: str | None,
        user_name: str | None,
        source_type: str | None,
        source_url: str | None,
        priority: str = "紧急",
    ) -> bool:
        """Notify n8n about a high priority issue.

        Args:
            entry_id: Entry ID
            title: Issue title
            type_tag: Type tag
            status_tag: Status tag
            feature_module: Feature module
            user_name: User name
            source_type: Source type
            source_url: Source URL
            priority: Priority level

        Returns:
            True if webhook sent successfully
        """
        payload = {
            "event": "high_priority_alert",
            "entry_id": entry_id,
            "title": title,
            "type_tag": type_tag,
            "status_tag": status_tag,
            "feature_module": feature_module,
            "user_name": user_name,
            "source_type": source_type,
            "source_url": source_url,
            "priority": priority,
            "crm_url": f"/entries/{entry_id}",
            "alert_level": "urgent",
        }

        return await self._send_webhook(self.high_priority_url, payload)

    async def send_feishu_notification(
        self,
        message: str,
        title: str | None = None,
    ) -> bool:
        """Send notification to Feishu.

        Args:
            message: Message content
            title: Optional title

        Returns:
            True if successful
        """
        if not self.feishu_webhook:
            return False

        payload = {
            "msg_type": "text",
            "content": {
                "text": f"{title}\n{message}" if title else message,
            },
        }

        try:
            async with httpx.AsyncClient(timeout=self.timeout) as client:
                response = await client.post(
                    self.feishu_webhook,
                    json=payload,
                    headers={"Content-Type": "application/json"},
                )
                return response.status_code < 400
        except Exception as e:
            print(f"Feishu webhook error: {e}")
            return False


# Global instance
_webhook_client: WebhookClient | None = None


def get_webhook_client() -> WebhookClient:
    """Get or create global webhook client instance."""
    global _webhook_client
    if _webhook_client is None:
        _webhook_client = WebhookClient()
    return _webhook_client


async def notify_new_issue(
    entry_id: str,
    title: str,
    type_tag: str,
    status_tag: str,
    feature_module: str | None = None,
    user_name: str | None = None,
    source_type: str | None = None,
    source_url: str | None = None,
    priority: str = "中",
) -> bool:
    """Convenience function to notify about new issue."""
    client = get_webhook_client()
    return await client.notify_new_issue(
        entry_id=entry_id,
        title=title,
        type_tag=type_tag,
        status_tag=status_tag,
        feature_module=feature_module,
        user_name=user_name,
        source_type=source_type,
        source_url=source_url,
        priority=priority,
    )


async def notify_high_priority(
    entry_id: str,
    title: str,
    type_tag: str,
    status_tag: str,
    feature_module: str | None = None,
    user_name: str | None = None,
    source_type: str | None = None,
    source_url: str | None = None,
    priority: str = "紧急",
) -> bool:
    """Convenience function to notify about high priority issue."""
    client = get_webhook_client()
    return await client.notify_high_priority(
        entry_id=entry_id,
        title=title,
        type_tag=type_tag,
        status_tag=status_tag,
        feature_module=feature_module,
        user_name=user_name,
        source_type=source_type,
        source_url=source_url,
        priority=priority,
    )
