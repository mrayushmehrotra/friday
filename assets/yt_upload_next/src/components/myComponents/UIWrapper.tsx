import { cn } from "@/lib/utils";

const UIWrapper = ({
  children,
  classname,
}: {
  children: React.ReactNode;
  classname: string;
}) => {
  return <div className={cn("p-24", classname)}>{children}</div>;
};

export default UIWrapper;
