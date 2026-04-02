import { Html, Head, Main, NextScript } from "next/document";

export default function Document() {
  return (
    <Html lang="ja">
      <Head>
        <link href="https://cdn.jsdelivr.net/npm/bootstrap@5.3.0/dist/css/bootstrap.min.css" rel="stylesheet" />
      </Head>
      <body className="min-h-screen bg-slate-50 font-sans text-slate-900 antialiased">
        <Main />
        <NextScript />
      </body>
    </Html>
  );
}
