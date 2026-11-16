export function Setup({ busy }: { busy: boolean }) {
  return (
    <section>
      <button className="primary" onClick={start}>
        Start session
      </button>
      <th>Status</th>
      <div>Bridge</div>
      <nav>
        Table
      </nav>
    </section>
  );
}
