import type { HelpCategory } from "./help_content";

export const HELP_CATEGORIES_EN: HelpCategory[] = [
  { id: "getting-started", icon: "bi-stars", title: "Getting started", items: [
    { question: "Is ChatCore-AI free?", answers: ["Yes. Creating an account and using the core features are free, with no credit card required."] },
    { question: "How do I create an account?", answers: ["Open the sign-up page and continue with your email address or Google account."], link: { href: "/register", label: "Open sign-up" } },
    { question: "Can I use it on a phone?", answers: ["Yes. It works in phone, tablet, and desktop browsers without an app install."] }
  ] },
  { id: "chat", icon: "bi-chat-square-text", title: "AI chat", items: [
    { question: "How do I start a chat?", answers: ["Type a question or task on the home page and send it. You can use Chat Core for research, drafts, brainstorming, and coding help."], link: { href: "/", label: "Open AI chat" } },
    { question: "Are chats saved?", answers: ["Chats are saved to your account unless you enable temporary chat. You can return to or delete saved conversations later."] },
    { question: "Are AI answers always accurate?", answers: ["AI can make mistakes. Verify sources before important decisions, and consult a qualified professional for medical, legal, or financial advice."] }
  ] },
  { id: "prompt-memo", icon: "bi-journal-text", title: "Prompts and memos", items: [
    { question: "What is the Prompt Library?", answers: ["It lets you find and reuse prompts from other users or publish your own. Never include private or confidential data in public prompts."], link: { href: "/prompt_share", label: "Browse prompts" } },
    { question: "How can I use memos?", answers: ["Save useful AI responses and your own notes, organize them for later, or create a share link for a selected memo."], link: { href: "/memo", label: "Open memos" } }
  ] },
  { id: "account", icon: "bi-person-gear", title: "Account and security", items: [
    { question: "Can I sign in without a password?", answers: ["Yes. Add a passkey from Settings > Security to sign in using your device unlock method."] },
    { question: "How do I change my email address?", answers: ["Open Settings > Security > Change email address and complete the verification steps for both addresses."] },
    { question: "What happens when I delete my account?", answers: ["Your saved chats, memos, prompts, and account data are deleted. See the privacy policy for details."], link: { href: "/privacy#retention", label: "Privacy policy: retention and deletion" } }
  ] },
  { id: "troubleshooting", icon: "bi-tools", title: "Troubleshooting", items: [
    { question: "I can’t log in", answers: ["Confirm that you are using the same email or Google account you registered with, then try again."], link: { href: "/login", label: "Open login" } },
    { question: "The AI does not respond", answers: ["A temporary service or network issue may be the cause. Wait briefly, retry, or reload the page."] }
  ] }
];
