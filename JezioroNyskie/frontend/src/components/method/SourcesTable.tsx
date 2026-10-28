import type { MethodSource } from '../../vm/useMethodVm';

export function SourcesTable({ rows }: { rows: MethodSource[] }) {
  return (
    <div className="sources">
      <table aria-label="Źródła danych">
        <thead>
          <tr>
            <th scope="col">Źródło</th>
            <th scope="col">Do czego</th>
            <th scope="col">Licencja</th>
          </tr>
        </thead>
        <tbody>
          {rows.map((r) => (
            <tr key={r.name}>
              <th scope="row">{r.name}</th>
              <td>{r.use}</td>
              <td>{r.license}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}
