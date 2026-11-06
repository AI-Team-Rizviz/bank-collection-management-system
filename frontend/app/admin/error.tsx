"use client";
import { Button } from "@/components/ui/button";
export default function ErrorPage({reset}:{reset:()=>void}){return <div className="error-state"><h2>Workspace unavailable</h2><p>An unexpected error interrupted the page.</p><Button onClick={reset}>Try again</Button></div>;}
