import { type NextRequest, NextResponse } from "next/server";
import Groq from "groq-sdk";

const groq = new Groq({ apiKey: process.env.GROQ_API_KEY });

export async function POST(request: NextRequest) {
  try {
    const { mood, context } = await request.json();

    if (!mood?.trim() || !context?.trim()) {
      return NextResponse.json(
        { error: "Mood and context are required" },
        { status: 400 },
      );
    }

    const prompt = `You are a Twitter/X content creator. Generate a tweet based on the following:

Mood: ${mood}
Context: ${context}

Requirements:
- Maximum 140 characters
- Engaging and natural
- No hashtags unless requested
- Return ONLY the tweet text, nothing else`;

    const completion = await groq.chat.completions.create({
      model: "llama-3.3-70b-versatile",
      messages: [{ role: "user", content: prompt }],
      temperature: 0.8,
      max_tokens: 100,
    });

    const tweet = completion.choices?.[0]?.message?.content?.trim() || "";

    return NextResponse.json({
      success: true,
      tweet: tweet.substring(0, 140),
    });
  } catch (error: any) {
    console.error("Generate tweet error:", error);
    return NextResponse.json(
      {
        success: false,
        error: error.message || "Failed to generate tweet",
      },
      { status: 500 },
    );
  }
}
