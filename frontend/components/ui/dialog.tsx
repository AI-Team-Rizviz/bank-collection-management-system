"use client";
import * as DialogPrimitive from "@radix-ui/react-dialog";
import { X } from "lucide-react";
import { cn } from "@/lib/utils";
export function Dialog({open,onOpenChange,title,description,children,wide=false}:{open:boolean;onOpenChange:(open:boolean)=>void;title:string;description:string;children:React.ReactNode;wide?:boolean}) {return <DialogPrimitive.Root open={open} onOpenChange={onOpenChange}><DialogPrimitive.Portal><DialogPrimitive.Overlay className="dialog-overlay"/><DialogPrimitive.Content className={cn("dialog-content",wide&&"dialog-wide")}><div className="dialog-head"><div><DialogPrimitive.Title>{title}</DialogPrimitive.Title><DialogPrimitive.Description>{description}</DialogPrimitive.Description></div><DialogPrimitive.Close className="icon-button" aria-label="Close dialog"><X size={18}/></DialogPrimitive.Close></div>{children}</DialogPrimitive.Content></DialogPrimitive.Portal></DialogPrimitive.Root>;}
