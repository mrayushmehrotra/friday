import { type NextRequest, NextResponse } from "next/server";
import Groq from "groq-sdk";

const groq = new Groq({ apiKey: process.env.GROQ_API_KEY });

export async function POST(request: NextRequest) {
  try {
    const { action, title, description, tags, targetAudience } =
      await request.json();

    if (action === "generateMetadata") {
      if (!title?.trim()) {
        return NextResponse.json(
          { error: "Title is required" },
          { status: 400 },
        );
      }

      const audience = targetAudience || "General Audience";

      const prompt = `You are a YouTube SEO expert. Given a video title, description, tags, and target audience, generate multiple suggestions for each.

Current title: "${title}"
Current description: "${description || "(none)"}"
Current tags: "${tags || "(none)"}"
Target audience: "${audience}"

Return ONLY valid JSON (no markdown, no code fences) with this exact structure:
{
  "titles": ["5-7 SEO-optimized, clickable title alternatives (max 100 chars each) that keep the original intent"],
  "descriptions": ["3-4 SEO-optimized description alternatives (2-3 sentences each, with relevant keywords)"],
  "tags": ["10-15 relevant hashtags and keywords (no # symbol, max 30 chars each)"],
  "general": "A brief paragraph of general SEO advice for this video based on its title, description, and target audience"
}`;

      const completion = await groq.chat.completions.create({
        model: "llama-3.3-70b-versatile",
        messages: [{ role: "user", content: prompt }],
        temperature: 0.8,
        max_tokens: 1000,
      });

      const content = completion.choices?.[0]?.message?.content || "";
      const parsed = JSON.parse(
        content.replace(/```json|```/g, "").trim(),
      );

      return NextResponse.json({
        success: true,
        hints: {
          titles: parsed.titles || [title],
          descriptions: parsed.descriptions || [description],
          tags: parsed.tags || [],
          general: parsed.general || "",
        },
      });
    }

    const { action: _a, ...rest } = await request.json();

    if (!rest.title?.trim()) {
      return NextResponse.json({ error: "Title is required" }, { status: 400 });
    }

    const prompt = `You are a YouTube SEO and Algorithm expert. Given a video title, optional description, and optional tags, generate improved SEO-friendly metadata which gain more views.

Current title: "${rest.title}"
Current description: "${rest.description || "(none)"}"
Current tags: "${rest.tags || "(none)"}"

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
      title: parsed.title?.substring(0, 100) || rest.title,
      description: parsed.description || rest.description,
      tags: parsed.tags || rest.tags,
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
