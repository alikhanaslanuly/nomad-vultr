import Link from "next/link";

export default function NotFound() {
  return (
    <section className="simple-page">
      <p className="eyebrow">404 / UNAVAILABLE</p>
      <h1>Outside the airlock.</h1>
      <p>This page is unavailable.</p>
      <Link className="primary-button" href="/">
        Start a new analysis →
      </Link>
    </section>
  );
}
