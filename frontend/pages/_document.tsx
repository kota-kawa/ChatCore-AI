import { Html, Head, Main, NextScript } from "next/document";

export default function Document() {
  return (
    <Html lang="ja">
      <Head>
        <link href="https://cdn.jsdelivr.net/npm/bootstrap@5.3.0/dist/css/bootstrap.min.css" rel="stylesheet" />
        <meta name="color-scheme" content="light dark" />
      </Head>
      <body className="min-h-screen font-sans antialiased">
        <Main />
        <NextScript />
      </body>
    </Html>
  );
}
