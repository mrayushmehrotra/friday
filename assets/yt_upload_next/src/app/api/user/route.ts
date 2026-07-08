import { type NextRequest, NextResponse } from "next/server";
import {
  User,
  checkSession,
} from "@/lib/models";

export async function GET(request: NextRequest) {
  try {
    const userId = request.cookies.get("user_id")?.value;

    if (!userId) {
      return NextResponse.json(
        { error: "Not authenticated", authenticated: false },
        { status: 401 },
      );
    }

    const session = await checkSession(userId);

    if (!session.valid || !session.user) {
      const response = NextResponse.json(
        { error: "Session expired", authenticated: false, expired: true },
        { status: 401 },
      );
      response.cookies.delete("user_id");
      response.cookies.delete("youtube_access_token");
      return response;
    }

    const user = session.user;

    return NextResponse.json({
      success: true,
      authenticated: true,
      user: {
        _id: user._id,
        email: user.email,
        name: user.name,
        image: user.image,
        youtubeChannelId: user.youtubeChannelId,
        youtubeChannelName: user.youtubeChannelName,
        youtubeChannelImage: user.youtubeChannelImage,
        youtubeConnectedAt: user.youtubeConnectedAt,
        sessionExpiresAt: user.sessionExpiresAt,
        plan: user.plan,
        createdAt: user.createdAt,
        updatedAt: user.updatedAt,
      },
      session: {
        expiresAt: session.expiresAt,
        remainingHours: session.remainingHours,
      },
    });
  } catch (error) {
    console.error("User API Error:", error);
    return NextResponse.json(
      { error: "Failed to fetch user data" },
      { status: 500 },
    );
  }
}
