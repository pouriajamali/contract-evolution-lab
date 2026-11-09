using Evolution;
using Xunit;
public class PolicyTests
{
    [Theory]
    [InlineData(1)] [InlineData(999999)] [InlineData(1000000)]
    public void CrossRepresentationHasOneBusinessIdentity(long value)
    {
        var old = Policy.Validate(1,"same-id",1,1,1,value,null);
        var next = Policy.Validate(2,"same-id",2,2,2,checked(value*1000),true);
        Assert.Equal(old,next);
        Assert.Equal(new System.Numerics.BigInteger(value),new System.Numerics.BigInteger(next.Ticks));
    }
    [Theory]
    [InlineData(null,1,1)] [InlineData(0,1,1)] [InlineData(2,1,1)]
    [InlineData(1,null,1)] [InlineData(1,0,1)] [InlineData(1,99,1)]
    [InlineData(1,1,null)] [InlineData(1,1,0)] [InlineData(1,1,99)]
    public void MissingOrUnknownSemanticsDeny(int? version,int? capability,int? unit)
    {
        Assert.Throws<ArgumentException>(()=>Policy.Validate(2,"x",(uint?)version,capability,unit,1,null));
    }
    [Fact] public void OldBinaryNeverAuthorizesNewUnits() => Assert.Throws<ArgumentException>(()=>Policy.Validate(1,"x",2,2,2,1000,true));
    [Theory] [InlineData(null)] [InlineData(false)]
    public void LostConfirmationDenies(bool? confirm) => Assert.Throws<ArgumentException>(()=>Policy.Validate(2,"x",2,2,2,1000,confirm));
    [Theory] [InlineData(0)] [InlineData(-1)] [InlineData(1000001)] [InlineData(long.MaxValue)]
    public void Boundaries(long ticks) => Assert.Throws<ArgumentException>(()=>Policy.Validate(2,"x",1,1,1,ticks,null));
    [Fact] public void FractionalMillitickConversionDenies() => Assert.Throws<ArgumentException>(()=>Policy.Validate(2,"x",2,2,2,1001,true));
    [Theory] [InlineData("")] [InlineData("CAPS")] [InlineData("a\nx")] [InlineData("../x")] [InlineData("x\n")] [InlineData("x\r\n")]
    public void IdentityFraming(string id) => Assert.Throws<ArgumentException>(()=>Policy.Validate(1,id,1,1,1,1,null));
}
