import type { Metadata } from 'next';
import './globals.css';
import { UserProvider } from '../contexts/UserContext';

export const metadata: Metadata = {
  title: 'LarkSync 控制台',
  description: '飞书文档同步任务的 Web 管控台',
};

export default function RootLayout({ children }: { children: React.ReactNode }): JSX.Element {
  return (
    <html lang="zh-Hans">
      <body>
        <UserProvider>
          <main>{children}</main>
        </UserProvider>
      </body>
    </html>
  );
}
