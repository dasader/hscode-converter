import type { HskCodeDetail } from '../api/types';

interface Props {
  node: HskCodeDetail;
  onSelect: (code: string) => void;
}

export default function HskTree({ node, onSelect }: Props) {
  return (
    <div style={{ marginLeft: (node.level - 1) * 20, padding: '4px 0' }}>
      <span onClick={() => onSelect(node.code)} style={{ cursor: 'pointer', fontFamily: 'monospace' }}>
        {node.code}
      </span>
      {' '}{node.name_kr}
      {node.children?.map((child) => (
        <HskTree key={child.code} node={child} onSelect={onSelect} />
      ))}
    </div>
  );
}
