import './styles.css';
export const metadata = { title: 'Chase Upside — Sports Network study', robots: { index: false, follow: false } };
export default function Layout({ children }) {
  return <html lang="en"><body>{children}</body></html>;
}
