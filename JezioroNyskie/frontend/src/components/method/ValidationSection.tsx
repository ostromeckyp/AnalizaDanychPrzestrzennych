import type { MethodValidation } from '../../vm/useMethodVm';

// Sekcja „Jak sprawdziliśmy model”: pięć kontroli i tabela zakresu błędu dna wg pasm wysokości.
// Tabela przewija się w własnym kontenerze (.sources), nie strona.
export function ValidationSection({ intro, checks, bands, lidarNote }: MethodValidation) {
  return (
    <section aria-labelledby="m-val">
      <h2 id="m-val">Jak sprawdziliśmy model</h2>
      <p className="method__note">{intro}</p>
      <ul className="checks" aria-label="Kontrole modelu">
        {checks.map((c) => (
          <li key={c.name}>
            <strong>{c.name}</strong> — {c.comparedWith}: {c.result}
          </li>
        ))}
      </ul>
      <h3 className="val__sub">Zakres błędu dna</h3>
      <div className="sources">
        <table aria-label="Zakres błędu dna">
          <thead>
            <tr>
              <th scope="col">wysokość dna</th>
              <th scope="col">typowy błąd</th>
              <th scope="col">główne źródło</th>
            </tr>
          </thead>
          <tbody>
            {bands.map((b) => (
              <tr key={b.label}>
                <th scope="row">{b.label}</th>
                <td>{b.range}</td>
                <td>
                  {b.dominant}
                  {b.note && <small className="val__note">{b.note}</small>}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      <p className="method__credit">{lidarNote}</p>
    </section>
  );
}
