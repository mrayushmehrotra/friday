import { type NextRequest, NextResponse } from "next/server";
import Groq from "groq-sdk";

const groq = new Groq({ apiKey: process.env.GROQ_API_KEY });

export async function POST(request: NextRequest) {
  try {
    const { title, description, tags } = await request.json();

    if (!title?.trim()) {
      return NextResponse.json({ error: "Title is required" }, { status: 400 });
    }

    const prompt = `You are a YouTube SEO and Algorithm expert. Given a video title, optional description, and optional tags, generate improved SEO-friendly metadata which gain more views.

Current title: "${title}"
Current description: "${description || "(none)"}"
Current tags: "${tags || "(none)"}"

Return ONLY valid JSON (no markdown, no code fences) with this exact structure:
{
  "title": "An SEO-optimized, clickable title (max 100 chars) that keeps the original intent",
  "description": "An SEO-optimized description (2-3 sentences with relevant keywords, max 500 chars)",
  "tags": "Comma-separated list of 8-15 relevant hashtags and keywords (no # symbol, max 30 chars each)"
}`;

    const completion = await groq.chat.completions.create({
      model: "llama-3.3-70b-versatile",
      messages: [{ role: "user", content: prompt }],
      temperature: 0.7,
      max_tokens: 500,
    });

    const content = completion.choices?.[0]?.message?.content || "";
    const parsed = JSON.parse(content.replace(/```json|```/g, "").trim());

    return NextResponse.json({
      success: true,
      title: parsed.title?.substring(0, 100) || title,
      description: parsed.description || description,
      tags: parsed.tags || tags,
    });
  } catch (error: any) {
    console.error("Groq API Error:", error);
    return NextResponse.json(
      {
        success: false,
        error: error.message || "Failed to generate suggestions",
      },
      { status: 500 },
    );
  }
}
