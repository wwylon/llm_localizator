export function Row({ on, done }: { on: boolean; done: boolean }) {
  return (
    <div>
      <button>{done ? 'Unmark cards as done' : 'Mark cards as done'}</button>
      <span>{on ? 'Show all rows' : 'Hide empty rows'}</span>
      <i title={on ? 'Currently enabled for you' : 'Currently disabled for you'} />
    </div>
  );
}
