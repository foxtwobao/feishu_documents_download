import type { Metadata } from 'next';
import './globals.css';

export const metadata: Metadata = {
  title: 'LarkSync - 飞书文档同步',
  description: '多用户飞书文档同步系统',
};

export default function RootLayout({
  children,
}: {
  children: React.ReactNode;
}) {
  return (
    <html lang="zh-CN">
      <head>
        <link
          rel="stylesheet"
          href="https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700&display=swap"
        />
      </head>
      <body className="font-sans antialiased">
        {children}
      </body>
    </html>
  );
}
