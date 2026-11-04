const base = { width: 20, height: 20, viewBox: "0 0 24 24", fill: "none", stroke: "currentColor",
  strokeWidth: 2, strokeLinecap: "round" as const, strokeLinejoin: "round" as const, "aria-hidden": true };

export const MenuIcon = () => <svg {...base}><path d="M4 7h16M4 12h16M4 17h10" /></svg>;
export const CloseIcon = () => <svg {...base}><path d="M6 6l12 12M18 6L6 18" /></svg>;
export const NewChatIcon = () => (
  <svg {...base}><path d="M12 20h9" /><path d="M16.5 3.5a2.1 2.1 0 0 1 3 3L7 19l-4 1 1-4z" /></svg>
);
export const SendIcon = () => (
  <svg {...base} width={18} height={18} strokeWidth={2.5}><path d="M12 19V5M5 12l7-7 7 7" /></svg>
);
export const LogoIcon = ({ size = 20 }: { size?: number }) => (
  <svg {...base} width={size} height={size}><path d="M4 19V9M10 19V5M16 19v-7M21 19H3" /></svg>
);
