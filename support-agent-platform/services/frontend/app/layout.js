import "./globals.css";

export const metadata = {
  title: "Support Agent — Console",
  description: "Single pane: submit tickets, watch the flow, approve high-risk actions, track cost.",
};

export default function RootLayout({ children }) {
  return (
    <html lang="en">
      <body>{children}</body>
    </html>
  );
}
