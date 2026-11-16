import i18n from './i18n';

export function Toolbar({ file }) {
  const err = i18n.__('The snippet must have at least 1 file');
  return (
    <div data-tip={i18n.__('save changes')}>
      <span>{i18n.__('Export JSON')}</span>
      <p>
        {i18n.__('Enable analytics to help improve it') +
          ' ' +
          i18n.__('and share usage')}
      </p>
      <h2>Please pick a snippet type</h2>
    </div>
  );
}
