import type { HskCodeDetail } from '../api/types';
import './HskTree.css';

interface Props {
  node: HskCodeDetail;
  onSelect: (code: string) => void;
}

export default function HskTree({ node, onSelect }: Props) {
  return (
    <div className="hsk-tree">
      {node.children?.map((child) => (
        <div key={child.code} className="tree-node" style={{ paddingLeft: `${(child.level - node.level) * 16}px` }}>
          <button className="tree-item" onClick={() => onSelect(child.code)}>
            <code className="tree-code">{child.code}</code>
            <span className="tree-name">{child.name_kr}</span>
          </button>
          {child.children && child.children.length > 0 && (
            <HskTree node={child} onSelect={onSelect} />
          )}
        </div>
      ))}
    </div>
  );
}
