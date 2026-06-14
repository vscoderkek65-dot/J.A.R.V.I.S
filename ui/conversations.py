from __future__ import annotations

import tkinter as tk

from ui.constants import C_BG, C_DIM, C_MID, C_PANEL, C_PRI, C_TEXT, font_body, font_body_bold


class ConversationsMixin:
    def _build_conversation_sidebar(self):
        self.conversation_panel = tk.Frame(
            self.root, bg=C_PANEL, highlightbackground=C_DIM, highlightthickness=1
        )
        header = tk.Frame(self.conversation_panel, bg=C_PANEL)
        header.pack(fill="x", padx=12, pady=(12, 8))
        tk.Label(
            header, text="SOHBETLER", fg=C_TEXT, bg=C_PANEL, font=font_body_bold(11)
        ).pack(side="left")
        tk.Button(
            header,
            text="+ YENİ",
            command=self._request_new_conversation,
            fg=C_BG,
            bg=C_PRI,
            activeforeground=C_BG,
            activebackground="#8ff8e6",
            borderwidth=0,
            font=font_body_bold(9),
            cursor="hand2",
        ).pack(side="right")
        self.conversation_list = tk.Listbox(
            self.conversation_panel,
            bg=C_PANEL,
            fg=C_TEXT,
            selectbackground=C_DIM,
            selectforeground=C_PRI,
            activestyle="none",
            borderwidth=0,
            highlightthickness=0,
            font=font_body(10),
        )
        self.conversation_list.pack(fill="both", expand=True, padx=8, pady=(0, 8))
        self.conversation_list.bind("<<ListboxSelect>>", self._conversation_selected)
        self._conversation_rows = []

    def set_conversations(self, conversations, active_id=""):
        def apply():
            self._conversation_rows = list(conversations or [])
            self.conversation_list.delete(0, tk.END)
            selected = None
            for index, item in enumerate(self._conversation_rows):
                title = str(item.get("title") or "Yeni sohbet").strip()
                self.conversation_list.insert(tk.END, "  " + title[:34])
                if item.get("id") == active_id:
                    selected = index
                    if hasattr(self, "chat_title"):
                        self.chat_title.configure(text=title[:48].upper())
            if selected is not None:
                self.conversation_list.selection_set(selected)
                self.conversation_list.activate(selected)

        self.root.after(0, apply)

    def load_conversation_messages(self, messages):
        def apply():
            self.typing_queue.clear()
            self.is_typing = False
            self.log_text.configure(state="normal")
            self.log_text.delete("1.0", tk.END)
            for item in messages or []:
                role = item.get("role", "")
                content = item.get("content", "")
                prefix = "Siz: " if role == "user" else "JARVIS: " if role == "assistant" else "SYS: "
                tag = "you" if role == "user" else "ai" if role == "assistant" else "sys"
                self.log_text.insert(tk.END, prefix + content + "\n\n", tag)
            self.log_text.configure(state="disabled")
            self.log_text.see(tk.END)

        self.root.after(0, apply)

    def _request_new_conversation(self):
        if self.on_new_conversation:
            self.on_new_conversation()

    def _conversation_selected(self, _event=None):
        selected = self.conversation_list.curselection()
        if not selected or not self.on_select_conversation:
            return
        self.on_select_conversation(self._conversation_rows[selected[0]]["id"])
