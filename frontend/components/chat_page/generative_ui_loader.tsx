import { memo, useEffect, useState } from "react";

// ローダーに巡回表示する進捗フレーズ。生成UIが「組み立てられていく」世界観に合わせる。
// Status phrases cycled inside the loader, themed around a UI being assembled.
const GENERATIVE_UI_LOADER_PHRASES = [
  "UIの設計図を広げています…",
  "部品を組み立てています…",
  "レイアウトを整えています…",
  "ボタンを磨いています…",
  "仕上げの輝きを足しています…",
];

// フレーズを切り替える間隔（ミリ秒）
// Interval between phrase switches (milliseconds)
const GENERATIVE_UI_LOADER_PHRASE_STEP_MS = 2200;

// 生成UIの作成中に表示する「UI組み立て工房」ローダー。
// ミニブラウザ画面の中でスケルトンUI部品が順番に組み上がり、
// スパークルのカーソルが画面を仕上げていくアニメーションを描く。
// "UI assembly atelier" loader shown while a generative UI is being produced.
// Inside a miniature browser window, skeleton UI parts build up in sequence
// while a sparkle cursor polishes the screen.
function GenerativeUiLoaderComponent() {
  const [phraseIndex, setPhraseIndex] = useState(0);

  // ウォールクロックに同期してフレーズを巡回させる（再マウントしても続きから見える）
  // Cycle phrases synchronized with the wall clock so remounts continue seamlessly
  useEffect(() => {
    let timerId: ReturnType<typeof setTimeout> | null = null;

    const syncPhrase = () => {
      const now = Date.now();
      setPhraseIndex(
        Math.floor(now / GENERATIVE_UI_LOADER_PHRASE_STEP_MS) % GENERATIVE_UI_LOADER_PHRASES.length,
      );
      const elapsedInStep = now % GENERATIVE_UI_LOADER_PHRASE_STEP_MS;
      timerId = setTimeout(syncPhrase, Math.max(48, GENERATIVE_UI_LOADER_PHRASE_STEP_MS - elapsedInStep + 18));
    };

    syncPhrase();

    return () => {
      if (timerId !== null) {
        clearTimeout(timerId);
      }
    };
  }, []);

  const phrase = GENERATIVE_UI_LOADER_PHRASES[phraseIndex] ?? GENERATIVE_UI_LOADER_PHRASES[0];

  return (
    <div className="genui-loader" role="status" aria-live="polite" aria-label="生成UIを作成しています">
      <div className="genui-loader__window" aria-hidden="true">
        <div className="genui-loader__titlebar">
          <span className="genui-loader__dot genui-loader__dot--1"></span>
          <span className="genui-loader__dot genui-loader__dot--2"></span>
          <span className="genui-loader__dot genui-loader__dot--3"></span>
          <span className="genui-loader__address"></span>
        </div>
        <div className="genui-loader__body">
          <span className="genui-loader__block genui-loader__block--hero"></span>
          <span className="genui-loader__block genui-loader__block--line"></span>
          <span className="genui-loader__block genui-loader__block--line genui-loader__block--line-short"></span>
          <span className="genui-loader__row">
            <span className="genui-loader__block genui-loader__block--card"></span>
            <span className="genui-loader__block genui-loader__block--card"></span>
            <span className="genui-loader__block genui-loader__block--card"></span>
          </span>
          <span className="genui-loader__block genui-loader__block--button"></span>
        </div>
        <span className="genui-loader__scanline"></span>
        <span className="genui-loader__sparkle">
          <span className="genui-loader__sparkle-core">✦</span>
          <span className="genui-loader__sparkle-trail"></span>
        </span>
      </div>
      <p className="genui-loader__status" key={phraseIndex}>
        {phrase}
      </p>
    </div>
  );
}

// フレーズ切り替え以外で再レンダリングされないようメモ化する
// Memoized so it only re-renders on phrase switches
export const GenerativeUiLoader = memo(GenerativeUiLoaderComponent);
GenerativeUiLoader.displayName = "GenerativeUiLoader";
