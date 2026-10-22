"use client";
export default function ErrorPage({ reset }: { reset: () => void }) {
  return (
    <main className="loading-workspace">
      <h1>The workspace could not open.</h1>
      <p>
        Your saved data has not been intentionally cleared. Try opening it
        again.
      </p>
      <button className="button button-primary" onClick={reset}>
        Try again
      </button>
    </main>
  );
}
