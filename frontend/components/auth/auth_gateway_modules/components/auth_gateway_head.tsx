import Head from "next/head";

export function AuthGatewayHead() {
  return (
    <Head>
      <meta charSet="UTF-8" />
      <meta name="viewport" content="width=device-width, initial-scale=1.0" />
      <title>Chat Core 認証</title>
      <link rel="icon" type="image/webp" href="/static/favicon.webp" />
      <link rel="icon" type="image/png" href="/static/favicon.png" />
      <link rel="apple-touch-icon" sizes="180x180" href="/static/apple-touch-icon.png" />
    </Head>
  );
}
