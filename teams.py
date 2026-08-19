"""
FarmWise Team Management
Farm owners can add workers who receive tasks and updates via WhatsApp.

Flow:
1. Owner types 'add worker Kwame 0241234567'
2. FarmWise saves Kwame as a team member
3. Owner types 'assign Kwame vaccinate batch 1 tomorrow'
4. FarmWise sends Kwame a WhatsApp message with the task
5. Kwame replies 'done' → owner gets notified

Roles:
- owner: full access, can add/remove workers, assign tasks
- manager: can assign tasks, view reports, but can't add/remove people
- worker: receives tasks, can mark done, can log daily data
"""

import os
import json
import logging
import re
from datetime import datetime, timezone

logger = logging.getLogger(__name__)
DATA_DIR = os.getenv("DATA_DIR", "./farm_data")


class TeamManager:
    """Manages farm teams — owners, managers, workers"""

    def __init__(self):
        os.makedirs(DATA_DIR, exist_ok=True)
        self.teams = {}
        self._load()

    def add_member(self, owner_phone, member_name, member_phone, role="worker"):
        """Add a team member to the owner's farm"""
        team = self._get_team(owner_phone)

        # Clean phone number
        member_phone = re.sub(r'[^\d]', '', member_phone)
        if member_phone.startswith('0') and len(member_phone) == 10:
            member_phone = '233' + member_phone[1:]

        # Check if already exists
        for m in team["members"]:
            if m["phone"] == member_phone:
                return f"{member_name} is already on your team."

        member = {
            "name": member_name,
            "phone": member_phone,
            "role": role,
            "added_at": datetime.now(timezone.utc).isoformat(),
            "tasks": [],
            "tasks_completed": 0,
        }
        team["members"].append(member)
        self._save()

        return (
            f"✅ *{member_name}* added to your team as {role}\n"
            f"Phone: {member_phone}\n\n"
            f"To assign a task:\n"
            f"'assign {member_name} vaccinate batch 1 tomorrow'"
        )

    def remove_member(self, owner_phone, member_name):
        """Remove a team member"""
        team = self._get_team(owner_phone)
        member_name_lower = member_name.lower()

        for i, m in enumerate(team["members"]):
            if m["name"].lower() == member_name_lower:
                removed = team["members"].pop(i)
                self._save()
                return f"✅ {removed['name']} removed from your team."

        return f"No team member named '{member_name}' found."

    def assign_task(self, owner_phone, member_name, task_text, send_func=None):
        """Assign a task to a team member"""
        team = self._get_team(owner_phone)
        member_name_lower = member_name.lower()

        member = None
        for m in team["members"]:
            if m["name"].lower() == member_name_lower:
                member = m
                break

        if not member:
            return f"No team member named '{member_name}'. Type 'team' to see your members."

        task = {
            "id": len(member["tasks"]) + 1,
            "text": task_text,
            "assigned_at": datetime.now(timezone.utc).isoformat(),
            "status": "pending",
            "completed_at": None,
        }
        member["tasks"].append(task)
        self._save()

        # Send WhatsApp message to worker if send function provided
        if send_func and member.get("phone"):
            owner_name = team.get("owner_name", "Your farm owner")
            send_func(
                member["phone"],
                f"📋 *New Task from {owner_name}*\n\n"
                f"{task_text}\n\n"
                f"Reply 'done' when finished."
            )

        return (
            f"✅ Task assigned to {member['name']}:\n"
            f"'{task_text}'\n\n"
            f"{'Message sent to their WhatsApp.' if send_func else 'Tell them directly.'}"
        )

    def complete_task(self, worker_phone, owner_phone=None):
        """Mark the latest pending task as done for a worker"""
        # Find which team this worker belongs to
        for team_owner, team in self.teams.items():
            for m in team["members"]:
                if m["phone"] == worker_phone:
                    # Find latest pending task
                    for task in reversed(m["tasks"]):
                        if task["status"] == "pending":
                            task["status"] = "completed"
                            task["completed_at"] = datetime.now(timezone.utc).isoformat()
                            m["tasks_completed"] += 1
                            self._save()
                            return {
                                "success": True,
                                "task": task["text"],
                                "worker_name": m["name"],
                                "owner_phone": team_owner,
                                "message": f"✅ Task completed: {task['text']}"
                            }
                    return {
                        "success": False,
                        "message": "No pending tasks to complete."
                    }

        return {"success": False, "message": "You're not assigned to any farm team."}

    def get_team_summary(self, owner_phone):
        """Show all team members and their status"""
        team = self._get_team(owner_phone)
        members = team["members"]

        if not members:
            return (
                "👥 *Your Team*\n\n"
                "No team members yet.\n\n"
                "Add someone:\n"
                "'add worker Kwame 0241234567'\n"
                "'add manager Ama 0551234567'"
            )

        msg = f"👥 *Your Team — {len(members)} members*\n\n"
        for m in members:
            pending = sum(1 for t in m["tasks"] if t["status"] == "pending")
            completed = m["tasks_completed"]
            role_emoji = "👔" if m["role"] == "manager" else "🧑‍🌾"

            msg += f"{role_emoji} *{m['name']}* ({m['role']})\n"
            msg += f"  Phone: {m['phone']}\n"
            if pending > 0:
                msg += f"  ⏳ {pending} pending task{'s' if pending != 1 else ''}\n"
            if completed > 0:
                msg += f"  ✅ {completed} completed\n"
            msg += "\n"

        msg += (
            "Commands:\n"
            "'assign Kwame clean pen today'\n"
            "'remove Kwame'\n"
            "'tasks' — see all pending tasks"
        )
        return msg

    def get_pending_tasks(self, owner_phone):
        """Show all pending tasks across the team"""
        team = self._get_team(owner_phone)
        members = team["members"]

        pending_tasks = []
        for m in members:
            for t in m["tasks"]:
                if t["status"] == "pending":
                    pending_tasks.append({
                        "worker": m["name"],
                        "task": t["text"],
                        "assigned": t["assigned_at"][:10],
                    })

        if not pending_tasks:
            return "✅ No pending tasks. Your team is all caught up!"

        msg = f"📋 *Pending Tasks ({len(pending_tasks)})*\n\n"
        for pt in pending_tasks:
            msg += f"• {pt['worker']}: {pt['task']} (assigned {pt['assigned']})\n"

        return msg

    def is_worker(self, phone):
        """Check if a phone number belongs to any farm worker"""
        for team_owner, team in self.teams.items():
            for m in team["members"]:
                if m["phone"] == phone:
                    return True, team_owner, m
        return False, None, None

    def parse_add_member(self, text):
        """
        Parse: 'add worker Kwame 0241234567'
        or: 'add manager Ama 0551234567'
        """
        match = re.match(
            r'add\s+(worker|manager)\s+(\w+)\s+([\d\s+\-]+)',
            text, re.IGNORECASE
        )
        if match:
            return {
                "role": match.group(1).lower(),
                "name": match.group(2).strip(),
                "phone": re.sub(r'[^\d]', '', match.group(3)),
            }
        return None

    def parse_assign(self, text):
        """
        Parse: 'assign Kwame vaccinate batch 1 tomorrow'
        """
        match = re.match(
            r'assign\s+(\w+)\s+(.+)',
            text, re.IGNORECASE
        )
        if match:
            return {
                "name": match.group(1).strip(),
                "task": match.group(2).strip(),
            }
        return None

    def set_owner_name(self, owner_phone, name):
        """Set the owner's display name for task notifications"""
        team = self._get_team(owner_phone)
        team["owner_name"] = name
        self._save()

    # ── Internal ──

    def _get_team(self, owner_phone):
        if owner_phone not in self.teams:
            self.teams[owner_phone] = {
                "owner_phone": owner_phone,
                "owner_name": "",
                "members": [],
                "created_at": datetime.now(timezone.utc).isoformat(),
            }
        return self.teams[owner_phone]

    def _save(self):
        filepath = os.path.join(DATA_DIR, "teams.json")
        try:
            with open(filepath, "w") as f:
                json.dump(self.teams, f, indent=2, default=str)
        except Exception as e:
            logger.error(f"Failed to save teams: {e}")

    def _load(self):
        filepath = os.path.join(DATA_DIR, "teams.json")
        try:
            with open(filepath, "r") as f:
                self.teams = json.load(f)
        except (FileNotFoundError, json.JSONDecodeError):
            self.teams = {}
